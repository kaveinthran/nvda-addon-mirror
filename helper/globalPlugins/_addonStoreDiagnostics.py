"""Local, evidence-labelled installed add-on diagnostics.

This deliberately reports configuration, loaded Python modules, and log lines
as different facts.  None of them is a claim about current CPU activity.
"""

import os
import sys
import threading

import wx


_LOG_TAIL_BYTES = 256 * 1024
_MAX_LOG_LINES = 10
_MAX_LOG_LINE_LENGTH = 300
_MODULE_KINDS = {
	"globalPlugins": "global plugin",
	"appModules": "app module",
	"synthDrivers": "synth driver",
	"brailleDisplayDrivers": "braille display driver",
	"visionEnhancementProviders": "vision enhancement provider",
}


def isSecureDesktop():
	"""Return true when local diagnostic UI must not expose information."""
	try:
		import globalVars
		if getattr(globalVars.appArgs, "secure", False):
			return True
	except (ImportError, AttributeError):
		pass
	try:
		from utils.security import isRunningOnSecureDesktop
		return bool(isRunningOnSecureDesktop())
	except ImportError:
		return False


def _underPath(filename, addonPath):
	if not isinstance(filename, str) or not isinstance(addonPath, str):
		return False
	try:
		return os.path.commonpath((os.path.realpath(filename), os.path.realpath(addonPath))) == os.path.realpath(addonPath)
	except (OSError, ValueError):
		return False


def loadedModuleEvidence(addon):
	"""Return loaded module labels for *addon*, without inferring activity."""
	labels = []
	for name, module in tuple(sys.modules.items()):
		if not _underPath(getattr(module, "__file__", None), getattr(addon, "path", None)):
			continue
		root = name.split(".", 1)[0]
		kind = _MODULE_KINDS.get(root, "add-on module")
		labels.append("%s: %s" % (kind, name))
	return sorted(set(labels), key=str.casefold)


def installedInventory(addonHandler):
	"""Collect configured state and module evidence for each installed add-on."""
	items = []
	for addon in addonHandler.getAvailableAddons():
		try:
			manifest = addon.manifest
			name = manifest.get("summary") or addon.name
		except Exception:
			continue
		disabled = bool(getattr(addon, "isDisabled", False) or getattr(addon, "isBlocked", False))
		items.append({
			"addon": addon,
			"addonId": addon.name,
			"name": name,
			"version": getattr(addon, "version", ""),
			"configured": "configured disabled" if disabled else "configured enabled",
			"loaded": loadedModuleEvidence(addon),
		})
	return sorted(items, key=lambda item: (item["name"].casefold(), item["addonId"].casefold()))


def _currentSessionLines(text):
	"""Return only the last identifiable NVDA session, otherwise no log evidence."""
	lines = text.splitlines()
	starts = [i for i, line in enumerate(lines) if "Starting NVDA" in line]
	return lines[starts[-1]:] if starts else []


def relatedLogEvidence(path, addonId, addonPath):
	"""Read a bounded local tail and return current-session references only."""
	if not isinstance(path, str) or not path:
		return [], "No current-session log file is configured."
	try:
		with open(path, "rb") as logFile:
			logFile.seek(0, os.SEEK_END)
			logFile.seek(max(0, logFile.tell() - _LOG_TAIL_BYTES))
			text = logFile.read().decode("utf-8", "replace")
	except OSError:
		return [], "The current-session log could not be read."
	lines = _currentSessionLines(text)
	if not lines:
		return [], "The log tail has no identifiable current-session boundary; no log evidence is shown."
	needles = tuple(value.casefold() for value in (addonId, addonPath) if isinstance(value, str) and value)
	matches = [line.strip()[:_MAX_LOG_LINE_LENGTH] for line in lines if any(needle in line.casefold() for needle in needles)]
	return matches[-_MAX_LOG_LINES:], "Current-session log references only; a reference does not prove activity."


def disableSelected(items, helperAddonId):
	"""Schedule exactly the supplied enabled add-ons for disable on restart."""
	# The helper starts unchecked so an all-enabled preview cannot disable the
	# diagnostic screen by accident. A user can explicitly check it, however.
	selected = [item for item in items if item["configured"] == "configured enabled"]
	for item in selected:
		item["addon"].enable(False)
	return selected


class DiagnosticsDialog(wx.Dialog):
	"""Keyboard-accessible checklist and readonly evidence viewer."""
	def __init__(self, parent, addonHandler, helperAddonId):
		super().__init__(parent, title=_("Installed add-on diagnostics"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._helperAddonId = helperAddonId
		self._items = installedInventory(addonHandler)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=_("Configured state and loaded-code evidence. Loaded code is not a claim that an add-on is currently active.")), 0, wx.ALL | wx.EXPAND, 10)
		self._list = wx.CheckListBox(self, choices=[self._label(item) for item in self._items])
		for index, item in enumerate(self._items):
			self._list.Check(index, item["addonId"] != helperAddonId and item["configured"] == "configured enabled")
		self._list.Bind(wx.EVT_LISTBOX, self._showEvidence)
		sizer.Add(self._list, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)
		sizer.Add(wx.StaticText(self, label=_("Evidence for selected add-on:")), 0, wx.ALL, 10)
		self._evidence = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
		sizer.Add(self._evidence, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)
		viewLogsButton = wx.Button(self, label=_("View related current-session log evidence"))
		viewLogsButton.Bind(wx.EVT_BUTTON, self._readRelatedLogs)
		sizer.Add(viewLogsButton, 0, wx.ALL, 10)
		buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		self.Bind(wx.EVT_BUTTON, self._disableChecked, id=wx.ID_OK)
		self.GetAffirmativeButton().SetLabel(_("Disable checked add-ons..."))
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
		self.SetSizerAndFit(sizer)
		self.SetMinSize((650, 450))
		if self._items:
			self._list.SetSelection(0)
			self._showEvidence(None)
		self._list.SetFocus()

	def _label(self, item):
		return "%s (%s): %s" % (item["name"], item["addonId"], item["configured"])

	def _showEvidence(self, evt):
		index = self._list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		item = self._items[index]
		loaded = "\n".join(item["loaded"]) or _("No loaded-module evidence found. This does not prove the add-on is inactive.")
		self._evidence.SetValue(_("Configured state: {state}\n\nLoaded-module evidence (loaded code, not activity):\n{loaded}\n\nCurrent-session related log evidence is read only when you choose View related log evidence.").format(state=item["configured"], loaded=loaded))

	def _readRelatedLogs(self, evt):
		index = self._list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		item = self._items[index]
		try:
			import globalVars
			logPath = getattr(globalVars.appArgs, "logFileName", None)
		except (ImportError, AttributeError):
			logPath = None
		def read():
			lines, note = relatedLogEvidence(str(logPath) if logPath else None, item["addonId"], getattr(item["addon"], "path", None))
			def finish():
				if not self.IsBeingDeleted():
					self._evidence.AppendText("\n\n%s\n%s" % (note, "\n".join(lines) or _("No related current-session log references found.")))
			wx.CallAfter(finish)
		threading.Thread(target=read, name="addonStoreDiagnosticsLog", daemon=True).start()

	def _disableChecked(self, evt):
		selected = [self._items[i] for i in range(len(self._items)) if self._list.IsChecked(i)]
		selected = [item for item in selected if item["configured"] == "configured enabled"]
		if not selected:
			wx.MessageBox(_("Select one or more configured enabled add-ons."), _("Disable add-ons"), wx.OK | wx.ICON_INFORMATION, self)
			return
		names = "\n".join(item["name"] for item in selected)
		answer = wx.MessageBox(_("The following add-ons will be disabled after NVDA restarts:\n\n{names}\n\nNo add-on files will be removed, and NVDA will not restart automatically. Continue?").format(names=names), _("Confirm disable add-ons"), wx.YES_NO | wx.ICON_WARNING, self)
		if answer != wx.YES:
			return
		try:
			disableSelected(selected, self._helperAddonId)
		except Exception as error:
			wx.MessageBox(_("NVDA could not schedule the selected add-ons for disable: {error}").format(error=error), _("Disable add-ons"), wx.OK | wx.ICON_ERROR, self)
			return
		wx.MessageBox(_("The selected add-ons are scheduled to be disabled when NVDA restarts. Restart NVDA when you are ready."), _("Disable add-ons"), wx.OK | wx.ICON_INFORMATION, self)
		self.EndModal(wx.ID_OK)


def showDiagnostics(parent, addonHandler, helperAddonId):
	if isSecureDesktop():
		return False
	dialog = DiagnosticsDialog(parent, addonHandler, helperAddonId)
	try:
		dialog.ShowModal()
	finally:
		dialog.Destroy()
	return True
