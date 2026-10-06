import builtins
import types
import unittest
from unittest import mock

from test_helper import HelperSourceSupportTests


class SharingSearchTests(unittest.TestCase):
    _loadHelper = HelperSourceSupportTests._loadHelper

    def setUp(self):
        self.helper = self._loadHelper({})
        self.messages = []
        self.copies = []
        self.api = types.ModuleType("api")
        self.api.copyToClip = lambda text: self.copies.append(text) or True
        self.ui = types.ModuleType("ui")
        self.ui.message = self.messages.append
        self.globalVars = types.ModuleType("globalVars")
        self.globalVars.appArgs = types.SimpleNamespace(secure=False)
        self.modules = {"api": self.api, "ui": self.ui, "globalVars": self.globalVars}

    def test_safe_urls_reject_credentials_schemes_and_controls(self):
        for url in (
            "file:///G:/private", "javascript:alert(1)", "https://user:secret@example.org/a",
            "https://example.org/\na", "https://example.org/a b", "https:///a",
            "https://example.org:bad/a", "https://example.org:99999/a",
            "https://example.org\\@evil.org/a", "https://example.org/\x7fa", None,
        ):
            with self.subTest(url=url):
                self.assertEqual("", self.helper._getSafeWebURL(url))
        url = "https://example.org/My%20Add-on.nvda-addon?x=1#asset"
        self.assertEqual(url, self.helper._getSafeWebURL(url))
        self.assertEqual("http://example.org/a", self.helper._getSafeWebURL("http://example.org/a"))

    def test_share_preserves_unicode_and_uses_source_then_homepage(self):
        model = types.SimpleNamespace(
            displayName="Tamil தமிழ்", description="Read français and 中文",
            sourceURL="https://github.com/example/addon", homepage="https://example.org/docs",
        )
        self.assertEqual(
            "Tamil தமிழ்\n\nRead français and 中文\n\nhttps://github.com/example/addon",
            self.helper._getShareText(model),
        )
        model.sourceURL = "file:///secret"
        self.assertTrue(self.helper._getShareText(model).endswith(model.homepage))
        self.assertEqual("", self.helper._getShareText(types.SimpleNamespace()))

    def test_scopes_do_not_match_other_fields_and_author_covers_both_models(self):
        model = types.SimpleNamespace(
            displayName="Clipboard tools", description="Search documents", addonId="clipTools",
            publisher="Cyrille", author="José", _serrebiStoreSource="Russian catalog",
        )
        match = self.helper._matchesSearchScope
        self.assertFalse(match(model, "documents", "title"))
        self.assertTrue(match(model, "documents", "description"))
        self.assertTrue(match(model, "CYRILLE", "author"))
        self.assertTrue(match(model, "JOSÉ", "author"))
        self.assertTrue(match(model, "CLIPTOOLS", "id"))
        self.assertTrue(match(model, "russian", "source"))
        self.assertFalse(match(model, "russian", "description"))

    def _makePlugin(self):
        class Action:
            def __init__(self, displayName, actionHandler, validCheck, actionTarget):
                self.displayName = displayName
                self.actionHandler = actionHandler
                self.validCheck = validCheck
                self.actionTarget = actionTarget

            @property
            def isValid(self):
                return self.actionTarget is not None and self.validCheck(self.actionTarget)

        class Store:
            def __init__(self, listVM):
                self.listVM = listVM

            def _makeActionsList(self):
                return ["core action"]

        class ListVM:
            def __init__(self, models):
                self._addons = {
                    name: types.SimpleNamespace(model=model, searchRank=lambda term: len(term))
                    for name, model in models.items()
                }
                self._filterString = "term"
                self._sortByModelField = types.SimpleNamespace(name="displayName")
                self._reverseSort = True
                self.selected = next(iter(self._addons.values()), None)
                self.raiseOnSort = False

            def _getFilteredSortedIds(self):
                if self.raiseOnSort:
                    raise RuntimeError("refresh failed")
                ordered = sorted(self._addons, reverse=self._reverseSort)
                if self._sortByModelField.name == "searchRank":
                    ordered.sort(
                        key=lambda name: self._addons[name].searchRank(self._filterString or ""),
                        reverse=self._reverseSort,
                    )
                return ordered

            def getSelection(self):
                return self.selected

        class Dialog:
            def _createFilterControls(self, helper):
                self.coreControlsCreated = True

            def onFilterTextChange(self, evt):
                self.nativeEvents.append(evt)

        actions = types.ModuleType("gui.addonStoreGui.viewModels.action")
        actions.AddonActionVM = Action
        stores = types.ModuleType("gui.addonStoreGui.viewModels.store")
        stores.AddonStoreVM = Store
        lists = types.ModuleType("gui.addonStoreGui.viewModels.addonList")
        lists.AddonListVM = ListVM
        dialogs = types.ModuleType("gui.addonStoreGui.controls.storeDialog")
        dialogs.AddonStoreDialog = Dialog
        self.modules.update({
            actions.__name__: actions, stores.__name__: stores,
            lists.__name__: lists, dialogs.__name__: dialogs,
        })
        plugin = self.helper.GlobalPlugin.__new__(self.helper.GlobalPlugin)
        plugin._sourceSupportPatches = []
        self.plugin = plugin
        return plugin, Store, ListVM, Dialog

    def _context(self):
        return mock.patch.dict("sys.modules", self.modules)

    def test_scoped_filter_preserves_order_and_restores_query_on_error(self):
        plugin, _, ListVM, _ = self._makePlugin()
        models = {
            "a": types.SimpleNamespace(displayName="other", description="term"),
            "b": types.SimpleNamespace(displayName="TERM"),
            "c": types.SimpleNamespace(displayName="term tools"),
        }
        with self._context():
            plugin._enableSharingAndScopedSearch()
            vm = ListVM(models)
            self.assertEqual(["c", "b", "a"], vm._getFilteredSortedIds())
            vm._serrebiSearchScope = "title"
            self.assertEqual(["c", "b"], vm._getFilteredSortedIds())
            self.assertEqual("term", vm._filterString)
            vm._sortByModelField.name = "searchRank"
            vm._addons["b"].searchRank = lambda term: 2 if term == "term" else 0
            vm._addons["c"].searchRank = lambda term: 1 if term == "term" else 0
            self.assertEqual(["b", "c"], vm._getFilteredSortedIds())
            vm.raiseOnSort = True
            with self.assertRaises(RuntimeError):
                vm._getFilteredSortedIds()
            self.assertEqual("term", vm._filterString)
            plugin._restoreSourceSupport()
            vm.raiseOnSort = False
            self.assertEqual(["a", "b", "c"], vm._getFilteredSortedIds())

    def test_actions_follow_core_target_changes_and_missing_download(self):
        plugin, Store, ListVM, _ = self._makePlugin()
        with self._context(), mock.patch.object(builtins, "_", lambda text: text, create=True):
            plugin._enableSharingAndScopedSearch()
            vm = ListVM({"a": types.SimpleNamespace(displayName="First", URL="https://example.org/a")})
            store = Store(vm)
            actions = store._makeActionsList()
            self.assertEqual("core action", actions[0])
            share, download = actions[1:]
            self.assertTrue(share.isValid)
            self.assertTrue(download.isValid)
            download.actionHandler(download.actionTarget)
            self.assertEqual(["https://example.org/a"], self.copies)
            self.copies.clear()
            self.messages.clear()
            vm.selected = types.SimpleNamespace(model=types.SimpleNamespace(displayName="Second"))
            # NVDA's _onSelectedItemChanged updates each persistent action target.
            for action in actions[1:]:
                action.actionTarget = vm.selected
            self.assertTrue(share.isValid)
            self.assertFalse(download.isValid)
            share.actionHandler(share.actionTarget)
            self.assertEqual(["Second"], self.copies)
            self.assertEqual(["Copied to clipboard"], self.messages)
            for action in actions[1:]:
                action.actionTarget = None
                self.assertFalse(action.isValid)

    def test_scope_choice_applies_pending_text_without_moving_focus(self):
        plugin, _, ListVM, Dialog = self._makePlugin()
        selections = []

        class Choice:
            def SetSelection(self, index):
                self.index = index

            def GetSelection(self):
                return self.index

            def Bind(self, event, handler):
                self.handler = handler

        class Sizer:
            def addLabeledControl(self, **kwargs):
                selections.append(kwargs)
                return Choice()

        with self._context(), mock.patch.object(builtins, "_", lambda text: text, create=True):
            plugin._enableSharingAndScopedSearch()
            dialog = Dialog()
            dialog._storeVM = types.SimpleNamespace(listVM=ListVM({}))
            dialog.searchFilterCtrl = types.SimpleNamespace(GetValue=lambda: "pending")
            applied = []
            dialog.filter = mock.Mock(side_effect=AssertionError("Native filter lifecycle bypassed"))
            dialog.onFilterTextChange = lambda evt: applied.append((evt, dialog.searchFilterCtrl.GetValue()))
            dialog._createFilterControls(Sizer())
            self.assertTrue(dialog.coreControlsCreated)
            self.assertEqual("Search &field:", selections[0]["labelText"])
            self.assertEqual(6, len(selections[0]["choices"]))
            dialog._serrebiSearchScopeCtrl.SetSelection(2)
            event = object()
            dialog._serrebiSearchScopeCtrl.handler(event)
            self.assertEqual("author", dialog._storeVM.listVM._serrebiSearchScope)
            self.assertEqual([(event, "pending")], applied)
            dialog.filter.assert_not_called()

    def test_clipboard_failure_and_secure_desktop(self):
        plugin, _, _, _ = self._makePlugin()
        with self._context(), mock.patch.object(builtins, "_", lambda text: text, create=True):
            self.api.copyToClip = mock.Mock(side_effect=OSError("busy"))
            plugin._copyStoreText("details")
            self.assertEqual(["Could not copy to clipboard"], self.messages)
            self.globalVars.appArgs.secure = True
            plugin._enableSharingAndScopedSearch()
            self.assertEqual([], plugin._sourceSupportPatches)
            plugin._copyStoreText("private")
            self.assertEqual(1, self.api.copyToClip.call_count)

    def test_choice_reaches_native_handler_when_typing_is_deferred(self):
        plugin, _, ListVM, Dialog = self._makePlugin()
        self.config.conf["serrebiStore"] = {"searchAsYouType": False}
        with self._context():
            plugin._enableDeferredSearch()
            plugin._enableSharingAndScopedSearch()
            dialog = Dialog()
            dialog._storeVM = types.SimpleNamespace(listVM=ListVM({}))
            dialog._serrebiSearchScopeCtrl = types.SimpleNamespace(GetSelection=lambda: 1)
            dialog.nativeEvents = []
            textEvent = types.SimpleNamespace(GetEventType=lambda: self.wx.wxEVT_TEXT, Skip=lambda: None)
            choiceEvent = types.SimpleNamespace(GetEventType=lambda: self.wx.wxEVT_CHOICE)
            dialog.onFilterTextChange(textEvent)
            self.assertEqual([], dialog.nativeEvents)
            plugin._onSearchScopeChange(dialog, choiceEvent)
            self.assertEqual([choiceEvent], dialog.nativeEvents)
            self.assertEqual("title", dialog._storeVM.listVM._serrebiSearchScope)

    def test_partial_install_rolls_back_own_patches_only(self):
        plugin, Store, _, _ = self._makePlugin()
        owner = types.SimpleNamespace(method="original")
        plugin._rememberPatch(owner, "method", "earlier")
        originalActions = Store._makeActionsList
        remember = plugin._rememberPatch
        calls = []

        def failSecond(owner, name, replacement):
            calls.append(name)
            if len(calls) == 2:
                raise RuntimeError("adapter unavailable")
            remember(owner, name, replacement)

        with self._context(), mock.patch.object(plugin, "_rememberPatch", failSecond):
            # The baseline fake logger turns reported exceptions into assertions.
            with self.assertRaises(AssertionError):
                plugin._enableSharingAndScopedSearch()
        self.assertIs(originalActions, Store._makeActionsList)
        self.assertEqual("earlier", owner.method)
        self.assertEqual(1, len(plugin._sourceSupportPatches))
