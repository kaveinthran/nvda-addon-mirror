"""Changelog support for the Add-on Store.

This module deliberately owns only its small cache and its patches.  It never
asks the Add-on Store downloader for an add-on package: GitHub's release API is
used only after the catalog has supplied a verified GitHub repository URL.
"""
import builtins
import json
import math
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_ = getattr(builtins, "_", lambda text: text)


CHANGELOG_KEY = "changelog"
RELEASE_TIME_KEY = "releaseTime"
MODEL_CHANGELOG_ATTRIBUTE = "_serrebiChangelog"
MODEL_RELEASE_TIME_ATTRIBUTE = "_serrebiReleaseTime"
_GITHUB_REPO = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)/?$")
CACHE_SECONDS = 15 * 60
MAX_RELEASES = 30
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CACHED_REPOSITORIES = 64


def githubRepository(sourceURL):
	"""Return ``owner/repository`` only for a safe, canonical GitHub page."""
	if not isinstance(sourceURL, str):
		return None
	match = _GITHUB_REPO.match(sourceURL.strip())
	if not match:
		return None
	return "%s/%s" % match.groups()


def releaseTime(model):
	"""A source release timestamp in milliseconds, or ``None`` when unknown."""
	value = getattr(model, MODEL_RELEASE_TIME_ATTRIBUTE, None)
	if type(value) in (int, float) and math.isfinite(value) and value > 0:
		return value
	value = getattr(model, "submissionTime", None)
	return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else None


def sortKey(model, descending=False):
	"""Unknown release times stay last in either direction."""
	value = releaseTime(model)
	if value is None:
		return (1, 0)
	return (0, -value if descending else value)


def isSecureDesktop():
	"""Fail closed when NVDA is running in its secure-desktop mode."""
	try:
		import globalVars
		return bool(globalVars.appArgs.secure)
	except (ImportError, AttributeError):
		return True


class ReleaseHistory:
	"""Small in-memory, TTL-bound GitHub release-notes cache."""
	def __init__(self, fetch=None, now=time.time):
		self._fetch = fetch or self._fetchJSON
		self._now = now
		self._cache = {}
		self._lock = threading.Lock()

	def get(self, repository):
		if not repository:
			return None, "notGitHub"
		with self._lock:
			cached = self._cache.get(repository)
			if cached and self._now() - cached[0] < CACHE_SECONDS:
				return cached[1], cached[2]
		try:
			releases = self._fetch(repository)
			if not isinstance(releases, list):
				raise ValueError("GitHub returned invalid release data")
			result, error = releases[:MAX_RELEASES], None
		except HTTPError as e:
			result, error = [], "rateLimit" if e.code in (403, 429) else "networkError"
		except (URLError, ValueError, OSError):
			result, error = [], "networkError"
		with self._lock:
			if repository not in self._cache and len(self._cache) >= MAX_CACHED_REPOSITORIES:
				del self._cache[next(iter(self._cache))]
			self._cache[repository] = (self._now(), result, error)
		return result, error

	@staticmethod
	def _fetchJSON(repository):
		url = "https://api.github.com/repos/%s/releases?per_page=%d" % (repository, MAX_RELEASES)
		request = Request(
			url,
			headers={"Accept": "application/vnd.github+json", "User-Agent": "NVDA-addonStoreMirror"},
		)
		with urlopen(request, timeout=10) as response:
			body = response.read(MAX_RESPONSE_BYTES + 1)
			if len(body) > MAX_RESPONSE_BYTES:
				raise ValueError("Release metadata exceeds the response limit")
			return json.loads(body.decode("utf-8"))


def _catalogNote(model):
	note = getattr(model, MODEL_CHANGELOG_ATTRIBUTE, "")
	return note.strip() if isinstance(note, str) else ""


def _fallback(model, reason):
	note = _catalogNote(model)
	if note:
		provenance = "catalog" if reason in ("missing", None) else "catalog; %s" % reason
		return [(getattr(model, "addonVersionName", "Latest"), note, provenance)]
	homepage = getattr(model, "homepage", None)
	if isinstance(homepage, str) and homepage.startswith(("https://", "http://")):
		# Translators: No changelog was found; this is the catalog's author page.
		return [("", _("No release notes are available. Author page: {url}").format(url=homepage), reason)]
	# Translators: The catalog and release-history service have no changelog for this add-on.
	return [("", _("No release notes are available for this add-on."), reason)]


def _provenanceLabel(source):
	# Translators: Origins and fallback reasons for changelog records.
	labels = {
		"catalog": _("Catalog notes"), "GitHub release": _("GitHub release"),
		"notGitHub": _("Release history unavailable for this source"),
		"rateLimit": _("Release service rate limit reached"),
		"networkError": _("Release service unavailable"), "missing": _("No release notes published"),
	}
	if isinstance(source, str) and source.startswith("catalog; "):
		return labels["catalog"] + "; " + labels.get(source.split("; ", 1)[1], _("History unavailable"))
	return labels.get(source, _("History unavailable"))


def historyForModel(model, history):
	"""Return version, notes, provenance records without inventing history."""
	repository = githubRepository(getattr(model, "sourceURL", None))
	releases, error = history.get(repository)
	if error:
		return _fallback(model, error)
	rows = []
	if _catalogNote(model):
		rows.append((getattr(model, "addonVersionName", "Latest"), _catalogNote(model), "catalog"))
	for release in releases:
		if not isinstance(release, dict):
			continue
		body = release.get("body")
		if isinstance(body, str) and body.strip():
			version = str(release.get("tag_name") or release.get("name") or _("Unknown version"))
			rows.append((version, body.strip(), "GitHub release"))
	return rows or _fallback(model, "missing")


class ChangelogFeature:
	def __init__(self, plugin):
		self.plugin = plugin
		self.history = ReleaseHistory()
		self._generation = 0

	def terminate(self):
		self._generation += 1

	def enable(self):
		if isSecureDesktop():
			return
		import importlib
		modelModule = importlib.import_module("addonStore.models.addon")
		storeModule = importlib.import_module("gui.addonStoreGui.viewModels.store")
		dataManager = None
		try:
			dataManager = importlib.import_module("addonStore.dataManager")
		except ImportError:
			pass
		for name in ("_createStoreModelFromData", "_createInstalledStoreModelFromData"):
			original = getattr(modelModule, name)
			def factory(data, _original=original):
				model = _original(data)
				for key, attribute in (
					(CHANGELOG_KEY, MODEL_CHANGELOG_ATTRIBUTE),
					(RELEASE_TIME_KEY, MODEL_RELEASE_TIME_ATTRIBUTE),
				):
					value = data.get(key)
					if isinstance(value, (str, int, float)):
						object.__setattr__(model, attribute, value)
				return model
			self.plugin._rememberPatch(modelModule, name, factory)
			if dataManager is not None and getattr(dataManager, name, None) is original:
				self.plugin._rememberPatch(dataManager, name, factory)
		base = modelModule._AddonGUIModel
		originalAsdict = base.asdict
		def asdict(model):
			data = originalAsdict(model)
			for key, attribute in (
				(CHANGELOG_KEY, MODEL_CHANGELOG_ATTRIBUTE),
				(RELEASE_TIME_KEY, MODEL_RELEASE_TIME_ATTRIBUTE),
			):
				value = getattr(model, attribute, None)
				if isinstance(value, (str, int, float)):
					data[key] = value
			return data
		self.plugin._rememberPatch(base, "asdict", asdict)
		self._patchSort(importlib)
		self._patchSortControl(importlib)
		self._patchAction(storeModule)

	def _patchSort(self, importlib):
		listModule = importlib.import_module("gui.addonStoreGui.viewModels.addonList")
		cls = listModule.AddonListVM
		original = cls._getFilteredSortedIds
		def filtered(vm):
			if not hasattr(vm, "_serrebiDateSort") or vm._serrebiDateSort is None:
				return original(vm)
			# Preserve core filtering, then replace only ordering. This also keeps
			# unknown dates last for both ascending and descending order.
			items = [vm._addons[addonId] for addonId in original(vm)]
			return [
				item.Id
				for item in sorted(items, key=lambda item: sortKey(item.model, vm._serrebiDateSort))
			]
		self.plugin._rememberPatch(cls, "_getFilteredSortedIds", filtered)
		originalSetSort = cls.setSortField
		def setSortField(vm, *args, **kwargs):
			vm._serrebiDateSort = None
			return originalSetSort(vm, *args, **kwargs)
		self.plugin._rememberPatch(cls, "setSortField", setSortField)
		choices = cls._columnSortChoices
		if isinstance(choices, property):
			def getChoices(vm):
				result = list(choices.__get__(vm, type(vm)))
				# Translators: An Add-on Store sort option using source release timestamps.
				result.append(_("Last updated (ascending)"))
				# Translators: An Add-on Store sort option using source release timestamps.
				result.append(_("Last updated (descending)"))
				return result
			self.plugin._rememberPatch(cls, "_columnSortChoices", property(getChoices))

	def _patchSortControl(self, importlib):
		"""Dispatch the two appended sort choices without adding a fake enum."""
		try:
			dialogModule = importlib.import_module("gui.addonStoreGui.controls.storeDialog")
		except ImportError:
			return
		cls = getattr(dialogModule, "AddonStoreDialog", None)
		if cls is None or not hasattr(cls, "onColumnFilterChange"):
			return
		original = cls.onColumnFilterChange
		def onColumnFilterChange(dialog, event):
			vm = dialog._storeVM.listVM
			choiceCount = len(vm._columnSortChoices)
			selection = event.GetSelection()
			if selection < choiceCount - 2:
				return original(dialog, event)
			oldOrder = vm._addonsFilteredOrdered
			vm._serrebiDateSort = bool(selection % 2)
			vm._updateAddonListing()
			if oldOrder != vm._addonsFilteredOrdered:
				try:
					import core
					core.callLater(delay=0, callable=vm.updated.notify)
				except ImportError:
					vm.updated.notify()
		self.plugin._rememberPatch(cls, "onColumnFilterChange", onColumnFilterChange)

	def _patchAction(self, storeModule):
		vmClass = storeModule.AddonStoreVM
		original = vmClass._makeActionsList
		feature = self
		def actions(vm):
			result = original(vm)
			try:
				from gui.addonStoreGui.viewModels.action import AddonActionVM
			except ImportError:
				return result
			# Translators: Add-on Store action that opens the selected add-on's release notes.
			result.append(AddonActionVM(
				displayName=_("&Changelog"),
				actionHandler=feature.show,
				validCheck=lambda item: item is not None and not isSecureDesktop(),
				actionTarget=vm.listVM.getSelection(),
			))
			return result
		self.plugin._rememberPatch(vmClass, "_makeActionsList", actions)

	def show(self, item):
		if item is None or isSecureDesktop():
			return
		import ui
		# Translators: Release history is being retrieved in the background.
		ui.message(_("Loading changelog."))
		generation = self._generation
		def worker():
			rows = historyForModel(item.model, self.history)
			if generation != self._generation:
				return
			try:
				import wx
				wx.CallAfter(self._showDialog, item.model.displayName, rows, generation)
			except Exception:
				return
		threading.Thread(target=worker, name="addonStoreChangelog", daemon=True).start()

	def _showDialog(self, name, rows, generation):
		if generation != self._generation or isSecureDesktop():
			return
		import wx
		from gui import mainFrame
		# Translators: Title of an Add-on Store dialog. {name} is the add-on name.
		dialog = wx.Dialog(mainFrame, title=_("Changelog: {name}").format(name=name))
		sizer = wx.BoxSizer(wx.VERTICAL)
		# Translators: Label for the release-version choice in the changelog viewer.
		sizer.Add(wx.StaticText(dialog, label=_("&Version and source:")), 0, wx.ALL, 8)
		choice = wx.Choice(dialog, choices=[
			"%s (%s)" % (version or _("Notes"), _provenanceLabel(source))
			for version, _notes, source in rows
		])
		sizer.Add(choice, 0, wx.EXPAND | wx.ALL, 8)
		# Translators: Label for the read-only changelog text.
		sizer.Add(wx.StaticText(dialog, label=_("Release &notes:")), 0, wx.LEFT | wx.RIGHT, 8)
		text = wx.TextCtrl(dialog, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		def choose(_evt=None):
			text.SetValue(rows[choice.GetSelection()][1])
		choice.Bind(wx.EVT_CHOICE, choose)
		choice.SetSelection(0)
		choose()
		sizer.Add(text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
		buttons = dialog.CreateButtonSizer(wx.OK)
		sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
		dialog.SetSizerAndFit(sizer)
		dialog.SetSize((650, 450))
		dialog.ShowModal()
		dialog.Destroy()
