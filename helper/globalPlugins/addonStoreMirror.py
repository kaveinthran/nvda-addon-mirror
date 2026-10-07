# SerrebiRadio NVDA Add-on Store Mirror helper.
# Points NVDA's built-in Add-on Store at the SerrebiRadio mirror, displays the
# winning upstream source for each catalog entry, adds Tools-menu entries to
# browse the official store and the mirror side by side, lets the store list
# filter only on demand instead of every keystroke, and warns instead of
# silently dropping duplicate add-ons selected for install/update.
# Adapted from nvdacn/NVDAUpdateMirror (GPL v2).
#
# NVDA 2025.1 is the floor. Earlier releases hardcode
# addonStore.network.BASE_URL and have no [addonStore] baseServerURL setting,
# so no add-on can redirect their Add-on Store anywhere.

import builtins
import importlib
import os
import threading
import weakref
from typing import Any
from urllib.parse import urlsplit

import wx

import addonHandler
import config
import globalPluginHandler
from logHandler import log

addonHandler.initTranslation()

MIRROR_STORE_URL = "https://serrebidev.github.io/nvda-addon-mirror"
# An empty baseServerURL means NVDA's official store.
OFFICIAL_STORE_URL = ""
STORE_SOURCE_KEY = "storeSource"
MODEL_SOURCE_ATTRIBUTE = "_serrebiStoreSource"
SEARCH_SCOPES = ("all", "title", "author", "description", "id", "source")

confspec = {
	"originalStoreURL": "string(default='')",
	"searchAsYouType": "boolean(default=True)",
}
config.conf.spec["serrebiStore"] = confspec
if "serrebiStore" not in config.conf:
	config.conf["serrebiStore"] = {}


def _getVmDisplayName(vm):
	"""Best-effort display name for an Add-on Store list item view model."""
	model = getattr(vm, "model", None)
	name = getattr(model, "displayName", None)
	if isinstance(name, str) and name.strip():
		return name.strip()
	return str(getattr(vm, "Id", "?"))


try:
	from gui.settingsDialogs import SettingsPanel as _SettingsPanelBase
except ImportError:  # pragma: no cover - only reachable outside NVDA
	_SettingsPanelBase = object


class SerrebiStoreSettingsPanel(_SettingsPanelBase):
	# Translators: The title of the SerrebiRadio add-on store settings panel.
	title = _("SerrebiRadio add-on store")

	def makeSettings(self, settingsSizer):
		try:
			searchAsYouType = config.conf["serrebiStore"]["searchAsYouType"]
		except KeyError:
			searchAsYouType = True
		checkBox = wx.CheckBox(
			self,
			# Translators: A setting controlling whether the Add-on Store
			# filters the list while typing. When off, the list only
			# filters when Enter is pressed in the search field.
			label=_("&Search while typing in the Add-on Store"),
		)
		# NVDA 2026.3 removed guiHelper.BoxSizer.addItem, so the settings
		# sizer is a plain wx sizer there. Use addItem where it exists and
		# fall back to Add otherwise.
		addItem = getattr(settingsSizer, "addItem", None)
		if addItem is not None:
			self._searchAsYouTypeCheckBox = addItem(checkBox)
		else:
			settingsSizer.Add(checkBox)
			self._searchAsYouTypeCheckBox = checkBox
		self._searchAsYouTypeCheckBox.SetValue(bool(searchAsYouType))

	def onSave(self):
		config.conf["serrebiStore"]["searchAsYouType"] = (
			self._searchAsYouTypeCheckBox.IsChecked()
		)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self._sourceSupportPatches = []
		self._toolsMenuItems = []
		self._movedStoreItem = None
		self._bundleMenu = None
		self._settingsPanelRegistered = False
		self._originalURL = ""
		self._urlApplied = False
		self._removeStaleBundleModule()
		try:
			currentURL = config.conf["addonStore"]["baseServerURL"]
		except KeyError:
			# Only reachable when compatibility was overridden: the manifest
			# requires 2025.1. Report it and change nothing, rather than patch
			# the Add-on Store GUI of an NVDA that can never use the mirror.
			log.error(
				"This NVDA has no [addonStore] baseServerURL setting, so its "
				"Add-on Store cannot be pointed at a mirror. NVDA 2025.1 or "
				"later is required.",
			)
			return
		savedURL = config.conf["serrebiStore"]["originalStoreURL"]
		# NVDA persists baseServerURL. On the next startup it may already point at
		# this mirror, so do not overwrite the remembered official/custom URL with
		# the mirror itself. Older helper builds could already have done that;
		# NVDA's empty default means "use the official store" and is safe here.
		if currentURL != MIRROR_STORE_URL:
			self._originalURL = currentURL
			config.conf["serrebiStore"]["originalStoreURL"] = currentURL
		else:
			self._originalURL = "" if savedURL == MIRROR_STORE_URL else savedURL
		config.conf["addonStore"]["baseServerURL"] = MIRROR_STORE_URL
		self._urlApplied = True
		log.info(f"Set the Add-on store mirror to: {MIRROR_STORE_URL}")
		self._enableSourceSupport()
		self._enableStoreEnhancements()
		self._addToolsMenuItems()
		self._registerSettingsPanel()
		self._refreshStore()

	def _rememberPatch(self, owner, name, replacement):
		"""Replace an attribute and remember enough state to restore it safely."""
		original = getattr(owner, name)
		setattr(owner, name, replacement)
		self._sourceSupportPatches.append((owner, name, original, replacement))

	def _enableSourceSupport(self):
		"""Preserve mirror provenance and add it to NVDA's Add-on Store list."""
		try:
			modelModule = importlib.import_module("addonStore.models.addon")
			listControlModule = importlib.import_module(
				"gui.addonStoreGui.controls.addonList"
			)
			listViewModelModule = importlib.import_module(
				"gui.addonStoreGui.viewModels.addonList"
			)
			# dataManager imports the model factories by name, so its copies
			# (used for the per-add-on installed cache) need patching as well.
			try:
				dataManagerModule = importlib.import_module("addonStore.dataManager")
			except ImportError:
				dataManagerModule = None

			for functionName in (
				"_createStoreModelFromData",
				"_createInstalledStoreModelFromData",
			):
				original = getattr(modelModule, functionName)

				def createModel(addonData, _original=original):
					model = _original(addonData)
					source = addonData.get(STORE_SOURCE_KEY)
					if isinstance(source, str) and source.strip():
						# Store models are frozen dataclasses, so normal assignment is
						# intentionally unavailable.
						object.__setattr__(model, MODEL_SOURCE_ATTRIBUTE, source.strip())
					return model

				self._rememberPatch(modelModule, functionName, createModel)
				if getattr(dataManagerModule, functionName, None) is original:
					self._rememberPatch(dataManagerModule, functionName, createModel)

			modelBase = modelModule._AddonGUIModel
			originalAsDict = modelBase.asdict

			def asdict(model):
				data = originalAsDict(model)
				source = _getModelSource(model)
				if source:
					# Preserve provenance in NVDA's per-add-on cache so installed
					# and update entries can keep displaying their source.
					data[STORE_SOURCE_KEY] = source
				return data

			self._rememberPatch(modelBase, "asdict", asdict)

			listControl = listControlModule.AddonVirtualList
			originalRefreshColumns = listControl._refreshColumns

			def refreshColumns(control):
				originalRefreshColumns(control)
				control.InsertColumn(
					control.GetColumnCount(),
					# Translators: The add-on catalog or release source shown in the Add-on Store.
					_("Source"),
					width=control.scaleSize(140),
				)

			self._rememberPatch(listControl, "_refreshColumns", refreshColumns)

			originalGetItemText = listControl.OnGetItemText

			def getItemText(control, itemIndex, colIndex):
				if colIndex == len(control._addonsListVM.presentedFields):
					return _getSourceAtIndex(control._addonsListVM, itemIndex)
				return originalGetItemText(control, itemIndex, colIndex)

			self._rememberPatch(listControl, "OnGetItemText", getItemText)

			originalColClick = listControl.OnColClick

			def onColClick(control, event):
				# Source is informational. Ignore its header rather than passing an
				# out-of-range field index to NVDA's built-in sorting code.
				if event.GetColumn() == len(control._addonsListVM.presentedFields):
					return
				return originalColClick(control, event)

			self._rememberPatch(listControl, "OnColClick", onColClick)

			listItemViewModel = listViewModelModule.AddonListItemVM
			searchableText = getattr(listItemViewModel, "searchableText", None)
			if isinstance(searchableText, property):
				def getSearchableText(listItem):
					text = searchableText.__get__(listItem, type(listItem))
					source = _getModelSource(listItem.model).casefold()
					return f"{text} {source}".strip()

				self._rememberPatch(
					listItemViewModel,
					"searchableText",
					property(getSearchableText, doc=searchableText.__doc__),
				)
			else:
				# NVDA 2025.1 through 2025.3 have no searchableText property and
				# filter inside _getFilteredSortedIds instead.
				listViewModel = listViewModelModule.AddonListVM
				originalFilteredIds = listViewModel._getFilteredSortedIds

				def getFilteredSortedIds(viewModel):
					filteredIds = originalFilteredIds(viewModel)
					term = viewModel._filterString
					if not term:
						return filteredIds
					sourceMatches = {
						item.Id
						for item in viewModel._addons.values()
						if term.casefold() in _getModelSource(item.model).casefold()
					}
					if not sourceMatches:
						return filteredIds
					savedFilter = viewModel._filterString
					try:
						viewModel._filterString = None
						allSortedIds = originalFilteredIds(viewModel)
					finally:
						viewModel._filterString = savedFilter
					included = set(filteredIds) | sourceMatches
					return [addonId for addonId in allSortedIds if addonId in included]

				self._rememberPatch(
					listViewModel,
					"_getFilteredSortedIds",
					getFilteredSortedIds,
				)
		except Exception:
			self._restoreSourceSupport()
			log.exception("Failed to add source information to the Add-on Store")
		else:
			log.info("Added source information to the Add-on Store")

	def _restoreSourceSupport(self):
		# Compare through the owner's own __dict__ so classmethod wrappers
		# compare against the exact object that was installed.
		for owner, name, original, replacement in reversed(self._sourceSupportPatches):
			try:
				current = owner.__dict__.get(name, None)
			except AttributeError:
				current = getattr(owner, name, None)
			if current is replacement:
				setattr(owner, name, original)
		self._sourceSupportPatches.clear()

	def _refreshStore(self):
		"""Refresh through NVDA's existing manager without replacing its singleton."""
		try:
			from addonStore import dataManager

			manager = dataManager.addonDataManager
			if manager is None:
				return

			def refresh():
				# Core starts an initial fetch before global plugins load. Let that
				# finish, then fetch again using the newly configured mirror URL.
				initial = getattr(manager, "_initialiseAvailableAddonsThread", None)
				if initial is not None and initial.is_alive():
					initial.join()
				if dataManager.addonDataManager is manager:
					manager.getLatestCompatibleAddons()

			threading.Thread(
				target=refresh,
				name="refreshAddonStoreMirror",
				daemon=True,
			).start()
		except Exception:
			log.exception("Failed to refresh the add-on store data manager")

	def terminate(self):
		self._removeToolsMenuItems()
		self._unregisterSettingsPanel()
		self._restoreSourceSupport()
		if not self._urlApplied:
			return
		config.conf["addonStore"]["baseServerURL"] = self._originalURL
		log.info(f"Restored the Add-on store URL to: {self._originalURL}")

	@property
	def _searchAsYouType(self):
		try:
			return bool(config.conf["serrebiStore"]["searchAsYouType"])
		except KeyError:
			return True

	def _enableStoreEnhancements(self):
		"""Backported store UX fixes: deferred search and duplicate warnings."""
		for enable in (
			self._enableDeferredSearch,
			self._enableDuplicateInstallWarning,
			self._enableSharingAndScopedSearch,
		):
			try:
				enable()
			except Exception:
				log.exception(
					f"SerrebiRadio store mirror could not enable {enable.__name__}",
				)

	def _enableSharingAndScopedSearch(self):
		"""Add read-only actions and explicit fields without replacing core filters."""
		if _isSecureContext():
			return
		start = len(self._sourceSupportPatches)
		try:
			actions = importlib.import_module("gui.addonStoreGui.viewModels.action")
			stores = importlib.import_module("gui.addonStoreGui.viewModels.store")
			lists = importlib.import_module("gui.addonStoreGui.viewModels.addonList")
			dialogs = importlib.import_module("gui.addonStoreGui.controls.storeDialog")
			storeClass = stores.AddonStoreVM
			listClass = lists.AddonListVM
			dialogClass = dialogs.AddonStoreDialog
			originalActionsList = storeClass._makeActionsList
			originalFilteredIds = listClass._getFilteredSortedIds
			originalCreateControls = dialogClass._createFilterControls
			plugin = self

			def makeActionsList(store):
				actionList = originalActionsList(store)
				if _isSecureContext():
					return actionList
				selected = store.listVM.getSelection()
				# Translators: Copies an add-on's name, description and source/homepage link.
				shareLabel = _("&Share add-on details")
				# Translators: Copies the download URL of the selected add-on release.
				downloadLabel = _("Copy download lin&k")
				for label, getText in (
					(shareLabel, lambda model: _getShareText(model)),
					(downloadLabel, lambda model: _getSafeWebURL(getattr(model, "URL", ""))),
				):
					actionList.append(actions.AddonActionVM(
						displayName=label,
						actionHandler=lambda item, getText=getText: plugin._copyStoreText(getText(item.model)),
						validCheck=lambda item, getText=getText: (
							not _isSecureContext() and bool(getText(item.model))
						),
						actionTarget=selected,
					))
				return actionList

			def getFilteredSortedIds(viewModel):
				ordered = originalFilteredIds(viewModel)
				scope = getattr(viewModel, "_serrebiSearchScope", "all")
				term = viewModel._filterString
				if scope == "all" or scope not in SEARCH_SCOPES or not term:
					return ordered
				# Narrow core's result using its real query and ordering. This retains
				# modern relevance ranking and the helper's source-search adapter.
				return [
					addonId for addonId in ordered
					if _matchesSearchScope(viewModel._addons[addonId].model, term, scope)
				]

			def createFilterControls(dialog, *args, **kwargs):
				originalCreateControls(dialog, *args, **kwargs)
				if _isSecureContext():
					return
				helper = args[0] if args else kwargs.get("filterCtrlHelper")
				if helper is None or not hasattr(helper, "addLabeledControl"):
					return
				# Translators: Search scope choice retaining the store's normal broad search.
				allText = _("All text")
				# Translators: Searches only an add-on's displayed title.
				title = _("Title")
				# Translators: Searches the installed author or catalog publisher.
				author = _("Author or publisher")
				# Translators: Searches only an add-on's description.
				description = _("Description")
				# Translators: Searches the add-on's internal manifest identifier.
				identifier = _("Add-on ID")
				# Translators: Searches the add-on's upstream catalog or release source.
				source = _("Source")
				dialog._serrebiSearchScopeCtrl = helper.addLabeledControl(
					# Translators: Label for the explicit field used by Add-on Store search.
					labelText=_("Search &field:"),
					wxCtrlClass=wx.Choice,
					choices=[allText, title, author, description, identifier, source],
				)
				dialog._serrebiSearchScopeCtrl.SetSelection(0)
				dialogRef = weakref.ref(dialog)
				def onScopeChange(evt):
					current = dialogRef()
					if current is not None:
						plugin._onSearchScopeChange(current, evt)
					else:
						evt.Skip()
				dialog._serrebiSearchScopeCtrl.Bind(
					wx.EVT_CHOICE,
					onScopeChange,
				)

			self._rememberPatch(storeClass, "_makeActionsList", makeActionsList)
			self._rememberPatch(listClass, "_getFilteredSortedIds", getFilteredSortedIds)
			self._rememberPatch(dialogClass, "_createFilterControls", createFilterControls)
		except Exception:
			# Keep provenance/deferred search patches installed before this family.
			self._restorePatchesFrom(start)
			log.exception("Failed to add sharing and scoped search to the Add-on Store")

	def _onSearchScopeChange(self, dialog, evt):
		if _isSecureContext():
			return
		index = dialog._serrebiSearchScopeCtrl.GetSelection()
		if not 0 <= index < len(SEARCH_SCOPES):
			return
		dialog._storeVM.listVM._serrebiSearchScope = SEARCH_SCOPES[index]
		# A scope choice is an explicit action: apply pending text even in
		# deferred mode. Typing still goes through the existing Enter policy.
		# Use core's text-change lifecycle (selection, relevance sort and sort
		# control synchronization). A Choice event bypasses deferred typing.
		dialog.onFilterTextChange(evt)

	def _copyStoreText(self, text):
		if _isSecureContext():
			return
		import api
		import ui

		try:
			copied = api.copyToClip(text)
		except Exception:
			copied = False
		if copied:
			# Translators: Confirmation after copying selected add-on metadata/link.
			ui.message(_("Copied to clipboard"))
		else:
			# Translators: Clipboard is unavailable; the selected text was not copied.
			ui.message(_("Could not copy to clipboard"))

	def _restorePatchesFrom(self, start):
		for owner, name, original, replacement in reversed(self._sourceSupportPatches[start:]):
			if owner.__dict__.get(name) is replacement:
				setattr(owner, name, original)
		del self._sourceSupportPatches[start:]

	def _enableDeferredSearch(self):
		"""Let the store list filter on demand instead of on every keystroke.

		NVDA filters on EVT_TEXT, so large lists re-filter per character. When
		the "search while typing" setting is off, per-keystroke events are
		ignored and the pending text is applied when Enter is pressed in the
		search field.
		"""
		try:
			storeDialogModule = importlib.import_module(
				"gui.addonStoreGui.controls.storeDialog",
			)
		except ImportError:
			log.debug("Add-on Store dialog module not found; deferred search unavailable")
			return
		dialogClass = getattr(storeDialogModule, "AddonStoreDialog", None)
		if dialogClass is None:
			return
		originalCreateFilterControls = getattr(
			dialogClass, "_createFilterControls", None,
		)
		originalOnFilterTextChange = getattr(
			dialogClass, "onFilterTextChange", None,
		)
		if originalCreateFilterControls is None or originalOnFilterTextChange is None:
			log.debug("Add-on Store dialog has no search filter to defer")
			return
		plugin = self

		def createFilterControls(dialog, *args, **kwargs):
			# Recent NVDA passes the sizer helper; older versions pass
			# nothing. Forward whatever is given.
			originalCreateFilterControls(dialog, *args, **kwargs)
			searchCtrl = getattr(dialog, "searchFilterCtrl", None)
			if searchCtrl is not None:
				dialogRef = weakref.ref(dialog)
				def onSearchKey(evt):
					current = dialogRef()
					if current is not None:
						plugin._onSearchCharHook(current, evt)
					else:
						evt.Skip()
				searchCtrl.Bind(
					# Windows consumes Enter during dialog navigation before a
					# plain TextCtrl receives EVT_KEY_DOWN. Catch it earlier.
					wx.EVT_CHAR_HOOK,
					onSearchKey,
				)

		def onFilterTextChange(dialog, evt):
			if not plugin._searchAsYouType and evt.GetEventType() == wx.wxEVT_TEXT:
				# Deferred mode: swallow the keystroke so the list is not
				# re-filtered; Enter in the search field applies it.
				evt.Skip()
				return None
			return originalOnFilterTextChange(dialog, evt)

		self._rememberPatch(dialogClass, "_createFilterControls", createFilterControls)
		self._rememberPatch(dialogClass, "onFilterTextChange", onFilterTextChange)

	def _onSearchCharHook(self, dialog, evt):
		if (
			evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
			and not self._searchAsYouType
		):
			# A key event is not a text event, so the onFilterTextChange
			# wrapper lets this through to NVDA's real filter. Not skipping
			# keeps Enter from activating the dialog's default button.
			dialog.onFilterTextChange(evt)
			return
		evt.Skip()

	def _enableDuplicateInstallWarning(self):
		"""Warn instead of silently dropping duplicate add-ons in a batch.

		NVDA's AddonStoreVM.getAddons logs and skips rows it cannot install,
		so selecting the same add-on twice (for example its stable and dev
		channels) silently installs only one of them. When duplicates are
		found, ask whether to install the first selected version of each
		add-on instead.
		"""
		try:
			storeModule = importlib.import_module(
				"gui.addonStoreGui.viewModels.store",
			)
		except ImportError:
			log.debug("AddonStoreVM not available; duplicate warning unavailable")
			return
		vmClass = getattr(storeModule, "AddonStoreVM", None)
		if vmClass is None:
			return
		# getAddons is a classmethod: keep the classmethod object itself so it
		# can be restored exactly.
		original = vmClass.__dict__.get("getAddons")
		if original is None:
			return

		def getAddons(cls, listItemVMs, *args, **kwargs):
			vms = list(listItemVMs)
			firstById = {}
			duplicateNames = set()
			for vm in vms:
				addonId = vm.Id
				if addonId in firstById:
					duplicateNames.add(_getVmDisplayName(vm))
				else:
					firstById[addonId] = vm
			if duplicateNames:
				if threading.current_thread() is threading.main_thread():
					import gui

					names = ", ".join(sorted(duplicateNames))
					answer = gui.messageBox(
						# Translators: Warning shown when the same add-on is
						# selected more than once for install or update, for
						# example its stable and dev channels.
						_(
							"You selected these add-ons more than once "
							"(for example the stable and dev versions of the same add-on): "
							"{names}. Only one copy of each add-on can be installed. "
							"Install the first selected version of each?",
						).format(names=names),
						# Translators: Title of the duplicate add-ons warning.
						_("Duplicate add-ons selected"),
						wx.YES_NO | wx.ICON_WARNING,
					)
					# gui.messageBox wraps wx.MessageBox, which answers wx.YES,
					# not the button id wx.ID_YES.
					if answer != wx.YES:
						return
				else:
					log.warning(
						"Duplicate add-ons in a background batch install; "
						f"keeping the first selected version of each: {sorted(duplicateNames)}",
					)
				vms = list(firstById.values())
			return original.__func__(cls, vms, *args, **kwargs)

		wrapper = classmethod(getAddons)
		setattr(vmClass, "getAddons", wrapper)
		self._sourceSupportPatches.append((vmClass, "getAddons", original, wrapper))

	def _removeStaleBundleModule(self):
		# Version 1.4.0 shipped the bundle code as globalPlugins/addonStoreBundles.py,
		# which NVDA's plugin loader mistakes for a global plugin and logs an error
		# for. It now lives in _addonStoreBundles.py (underscore-prefixed modules are
		# skipped by the loader); remove the stale file if an update left it behind.
		stale = os.path.join(os.path.dirname(__file__), "addonStoreBundles.py")
		try:
			if os.path.isfile(stale):
				os.remove(stale)
				log.info("Removed stale bundle module left by addonStoreMirror 1.4.0")
		except OSError:
			log.warning("Could not remove stale bundle module", exc_info=True)

	def _addToolsMenuItems(self):
		"""Group the existing store command and the official store in a submenu."""
		try:
			import gui
		except ImportError:
			return
		try:
			sysTrayIcon = gui.mainFrame.sysTrayIcon
			toolsMenu = sysTrayIcon.toolsMenu
		except AttributeError:
			log.debug("Tools menu not available; skipping store menu item")
			return
		storeMenu = wx.Menu()
		self._movedStoreItem = None
		# Use NVDA's translation for its own item, preserving its id and handler.
		regularItem = toolsMenu.FindItemById(toolsMenu.FindItem(builtins._("&Add-on store...")))
		if regularItem is not None:
			position = list(toolsMenu.GetMenuItems()).index(regularItem)
			toolsMenu.Remove(regularItem)
			storeMenu.Append(regularItem)
			self._movedStoreItem = (storeMenu, regularItem, position)
		# Translators: Opens NVDA's official Add-on Store.
		officialItem = storeMenu.Append(
			wx.ID_ANY, _("&Official NVDA store..."),
		)
		sysTrayIcon.Bind(wx.EVT_MENU, self._onBrowseOfficialStore, officialItem)
		# Translators: Tools submenu containing the mirror and official stores.
		self._toolsMenuItems = [toolsMenu.AppendSubMenu(storeMenu, _("&Add-on Store"))]
		self._addBundleMenuItems(toolsMenu, sysTrayIcon)
		log.info("Grouped Add-on Store items in the Tools menu")

	def _addBundleMenuItems(self, toolsMenu, sysTrayIcon):
		"""Add the Add-on bundles submenu (export/import) to the Tools menu."""
		bundleMenu = wx.Menu()
		# Translators: Tools menu item exporting installed add-ons as a bundle file.
		exportItem = bundleMenu.Append(
			wx.ID_ANY, _("Export installed add-ons as bundle..."),
		)
		sysTrayIcon.Bind(wx.EVT_MENU, self._onExportBundle, exportItem)
		# Translators: Tools menu item installing add-ons from a bundle file.
		importItem = bundleMenu.Append(
			wx.ID_ANY, _("Install add-ons from bundle file..."),
		)
		sysTrayIcon.Bind(wx.EVT_MENU, self._onImportBundle, importItem)
		# Translators: Tools submenu for add-on bundle export/import.
		subMenuItem = toolsMenu.AppendSubMenu(bundleMenu, _("Add-on bundles..."))
		self._toolsMenuItems.append(subMenuItem)
		self._bundleMenu = bundleMenu

	def _onExportBundle(self, evt):
		try:
			from . import _addonStoreBundles as addonStoreBundles
			import addonHandler
			import gui
		except ImportError:
			return
		installed = addonStoreBundles.getInstalledAddons(addonHandler)
		if not installed:
			wx.MessageBox(
				# Translators: Shown when exporting a bundle with no add-ons installed.
				_("There are no installed add-ons to export."),
				_("Export add-on bundle"),
				wx.OK | wx.ICON_INFORMATION,
			)
			return
		dialog = addonStoreBundles.ExportBundleDialog(gui.mainFrame, installed)
		try:
			dialog.ShowModal()
		finally:
			dialog.Destroy()

	def _onImportBundle(self, evt):
		try:
			from . import _addonStoreBundles as addonStoreBundles
			import addonHandler
			import gui
		except ImportError:
			return
		# Translators: File dialog title and filter for opening a bundle.
		wildcard = _("NVDA add-on bundle (*%s)|*%s") % (
			addonStoreBundles.BUNDLE_EXTENSION, addonStoreBundles.BUNDLE_EXTENSION,
		)
		with wx.FileDialog(
			gui.mainFrame, _("Choose an add-on bundle"), wildcard=wildcard,
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		) as fileDialog:
			if fileDialog.ShowModal() != wx.ID_OK:
				return
			path = fileDialog.GetPath()
		try:
			bundle = addonStoreBundles.loadBundleFile(path)
		except addonStoreBundles.BundleError as e:
			wx.MessageBox(str(e), _("Install from add-on bundle"), wx.OK | wx.ICON_ERROR)
			return
		try:
			catalogMap = addonStoreBundles.runPumped(addonStoreBundles.fetchCatalogMap)
		except Exception:
			log.warning("Could not fetch the mirror catalog for bundle import", exc_info=True)
			catalogMap = {}
		installedMap = {
			item["addonId"]: item
			for item in addonStoreBundles.getInstalledAddons(addonHandler)
		}
		dialog = addonStoreBundles.ImportBundleDialog(gui.mainFrame, bundle, catalogMap, installedMap)
		try:
			dialog.ShowModal()
		finally:
			dialog.Destroy()

	def _removeToolsMenuItems(self):
		if not self._toolsMenuItems:
			return
		try:
			import gui

			toolsMenu = gui.mainFrame.sysTrayIcon.toolsMenu
		except (ImportError, AttributeError):
			self._toolsMenuItems = []
			self._bundleMenu = None
			self._movedStoreItem = None
			return
		if self._movedStoreItem is not None:
			storeMenu, regularItem, position = self._movedStoreItem
			storeMenu.Remove(regularItem)
			toolsMenu.Insert(position, regularItem)
			self._movedStoreItem = None
		for item in self._toolsMenuItems:
			toolsMenu.DestroyItem(item)
		self._toolsMenuItems = []
		self._bundleMenu = None

	def _registerSettingsPanel(self):
		try:
			import gui.settingsDialogs
		except ImportError:
			return
		panelClasses = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
		if SerrebiStoreSettingsPanel not in panelClasses:
			panelClasses.append(SerrebiStoreSettingsPanel)
			self._settingsPanelRegistered = True

	def _unregisterSettingsPanel(self):
		if not self._settingsPanelRegistered:
			return
		try:
			import gui.settingsDialogs

			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(
				SerrebiStoreSettingsPanel,
			)
		except (ImportError, ValueError):
			pass
		self._settingsPanelRegistered = False

	def _onBrowseOfficialStore(self, evt):
		# An empty baseServerURL is NVDA's official store; switch back to the
		# mirror when that dialog closes.
		self._openStore(OFFICIAL_STORE_URL, restoreURL=MIRROR_STORE_URL)

	def _openStore(self, url, restoreURL):
		"""Open the Add-on Store at the given URL.

		When restoreURL is given, the configured URL is switched back and the
		data manager refreshed when the dialog closes.
		"""
		import gui
		from gui import SettingsDialog
		from gui.addonStoreGui import AddonStoreDialog
		from gui.addonStoreGui.viewModels.store import AddonStoreVM

		for win in wx.GetTopLevelWindows():
			if isinstance(win, AddonStoreDialog):
				win.Raise()
				win.SetFocus()
				return
		previousURL = config.conf["addonStore"]["baseServerURL"]
		config.conf["addonStore"]["baseServerURL"] = url
		try:
			storeVM = AddonStoreVM()
			storeVM.refresh()
			prePopup = getattr(gui.mainFrame, "prePopup", None)
			if prePopup is not None:
				prePopup()
			try:
				dialog = AddonStoreDialog(gui.mainFrame, storeVM)
			except SettingsDialog.MultiInstanceErrorWithDialog as error:
				config.conf["addonStore"]["baseServerURL"] = previousURL
				error.dialog.SetFocus()
				return
			if restoreURL is not None:
				# Not EVT_CLOSE: NVDA's Close button destroys the dialog
				# directly (SettingsDialog.onClose -> DestroyLater) without
				# one, so only the destroy event is seen on every way out.
				dialog.Bind(wx.EVT_WINDOW_DESTROY, self._makeCloseRestorer(dialog, restoreURL))
			dialog.Show()
		except Exception:
			config.conf["addonStore"]["baseServerURL"] = previousURL
			log.exception("Failed to open the Add-on Store")
			return
		finally:
			postPopup = getattr(gui.mainFrame, "postPopup", None)
			if postPopup is not None:
				postPopup()

	def _makeCloseRestorer(self, dialog, restoreURL):
		dialogRef = weakref.ref(dialog)
		def onDestroy(evt):
			# Destroy events from child controls reach the dialog too.
			current = dialogRef()
			if current is not None and evt.GetEventObject() is current:
				config.conf["addonStore"]["baseServerURL"] = restoreURL
				self._refreshStore()
			evt.Skip()

		return onDestroy


def _getModelSource(model):
	source = getattr(model, MODEL_SOURCE_ATTRIBUTE, "")
	return source if isinstance(source, str) else ""


def _isSecureContext() -> bool:
	try:
		import globalVars
		return bool(globalVars.appArgs.secure)
	except (ImportError, AttributeError):
		return True


def _getSafeWebURL(value: Any) -> str:
	"""Return an uncredentialed HTTP(S) URL, or empty text for unusable metadata."""
	if not isinstance(value, str) or any(char.isspace() or not char.isprintable() for char in value):
		return ""
	try:
		parsed = urlsplit(value)
		if parsed.scheme not in ("https", "http") or not parsed.hostname:
			return ""
		if parsed.username is not None or parsed.password is not None or "\\" in value:
			return ""
		# Accessing port validates an explicit port's range and spelling.
		parsed.port
	except ValueError:
		return ""
	return value


def _getShareText(model: Any) -> str:
	parts = []
	for field in ("displayName", "description"):
		value = getattr(model, field, "")
		if isinstance(value, str) and value.strip():
			parts.append(value.strip())
	url = _getSafeWebURL(getattr(model, "sourceURL", ""))
	if not url:
		url = _getSafeWebURL(getattr(model, "homepage", ""))
	if url:
		parts.append(url)
	return "\n\n".join(parts)


def _matchesSearchScope(model: Any, term: str, scope: str) -> bool:
	fields = {
		"title": ("displayName",),
		"author": ("author", "publisher"),
		"description": ("description",),
		"id": ("addonId",),
	}
	if scope == "source":
		return term.casefold() in _getModelSource(model).casefold()
	return any(
		term.casefold() in value.casefold()
		for field in fields.get(scope, ())
		if isinstance(value := getattr(model, field, ""), str)
	)


def _getSourceAtIndex(listViewModel, index):
	"""Return provenance for a row across both old and current NVDA list VMs."""
	try:
		getAddon = getattr(listViewModel, "getAddonAtIndex", None)
		if getAddon is not None:
			return _getModelSource(getAddon(index).model)
		addonId = listViewModel._addonsFilteredOrdered[index]
		return _getModelSource(listViewModel._addons[addonId].model)
	except (AssertionError, IndexError, KeyError):
		# A background refresh can replace the model between wx requesting a
		# virtual row and requesting its column text.
		return ""
