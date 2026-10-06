import builtins
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "helper" / "globalPlugins" / "_addonStoreDiagnostics.py"


def loadDiagnostics(extraModules=None):
    """Load the utility module with the wx surface needed to define its dialog."""
    wx = types.ModuleType("wx")
    wx.Dialog = object
    modules = {"wx": wx, **(extraModules or {})}
    spec = importlib.util.spec_from_file_location("diagnostics_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules), mock.patch.object(builtins, "_", lambda text: text, create=True):
        spec.loader.exec_module(module)
    return module


class DiagnosticsEvidenceTests(unittest.TestCase):
    def test_pending_log_callback_is_discarded_after_selection_changes(self):
        diagnostics = loadDiagnostics()
        callbacks = []
        diagnostics.wx.NOT_FOUND = -1
        diagnostics.wx.CallAfter = callbacks.append
        dialog = object.__new__(diagnostics.DiagnosticsDialog)
        dialog._generation = 0
        dialog._list = types.SimpleNamespace(GetSelection=lambda: 0)
        dialog._items = [{
            "addonId": "one", "addon": types.SimpleNamespace(path="G:/addons/one"),
            "loaded": [], "configured": "configured enabled",
        }]
        dialog._evidence = types.SimpleNamespace(SetValue=lambda value: None, AppendText=mock.Mock())
        dialog.IsBeingDeleted = lambda: False
        thread = lambda **kwargs: types.SimpleNamespace(start=kwargs["target"])
        with mock.patch.object(diagnostics, "isSecureDesktop", return_value=False), \
            mock.patch.object(diagnostics.threading, "Thread", side_effect=thread), \
            mock.patch.object(diagnostics, "relatedLogEvidence", return_value=(["old selected log"], "note")), \
            mock.patch.object(builtins, "_", lambda text: text, create=True):
            dialog._readRelatedLogs(None)
            dialog._showEvidence(None)
            callbacks[0]()
        dialog._evidence.AppendText.assert_not_called()

    def test_loaded_modules_are_mapped_by_real_addon_path(self):
        diagnostics = loadDiagnostics()
        addon = types.SimpleNamespace(path="G:/addons/example")
        module = types.SimpleNamespace(__file__="G:/addons/example/globalPlugins/example.py")
        outside = types.SimpleNamespace(__file__="G:/addons/exampleElse/appModules/no.py")
        with mock.patch.object(
            diagnostics.sys,
            "modules",
            {"addons.example.globalPlugins.example": module, "addons.example.appModules.no": outside},
        ):
            self.assertEqual(
                ["global plugin: addons.example.globalPlugins.example"],
                diagnostics.loadedModuleEvidence(addon),
            )

    def test_log_requires_a_current_session_boundary_and_is_bounded(self):
        diagnostics = loadDiagnostics()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as logFile:
            logFile.write("old addonId\n")
            path = logFile.name
        try:
            lines, note = diagnostics.relatedLogEvidence(path, "addonId", "C:/none")
            self.assertEqual([], lines)
            self.assertIn("boundary", note)
            with open(path, "w", encoding="utf-8") as logFile:
                logFile.write("Starting NVDA\n" + "\n".join("addonId evidence %d" % i for i in range(15)))
            lines, note = diagnostics.relatedLogEvidence(path, "addonId", "C:/none")
            self.assertEqual(10, len(lines))
            self.assertIn("does not prove", note)
        finally:
            Path(path).unlink()

    def test_disable_only_enabled_addons_and_allows_deliberate_helper_selection(self):
        diagnostics = loadDiagnostics()
        enabled = types.SimpleNamespace(calls=[])
        enabled.enable = lambda value: enabled.calls.append(value)
        helper = types.SimpleNamespace(calls=[])
        helper.enable = lambda value: helper.calls.append(value)
        disabled = types.SimpleNamespace(calls=[])
        disabled.enable = lambda value: disabled.calls.append(value)
        selected = diagnostics.disableSelected([
            {"addonId": "one", "configured": "configured enabled", "addon": enabled},
            {"addonId": "addonStoreMirror", "configured": "configured enabled", "addon": helper},
            {"addonId": "two", "configured": "configured disabled", "addon": disabled},
        ], "addonStoreMirror")
        self.assertEqual([False], enabled.calls)
        self.assertEqual([False], helper.calls)
        self.assertEqual([], disabled.calls)
        self.assertEqual(["one", "addonStoreMirror"], [item["addonId"] for item in selected])

    def test_secure_guard_uses_command_line_secure_flag(self):
        globalVars = types.ModuleType("globalVars")
        globalVars.appArgs = types.SimpleNamespace(secure=True)
        diagnostics = loadDiagnostics()
        with mock.patch.dict(sys.modules, {"globalVars": globalVars}):
            self.assertTrue(diagnostics.isSecureDesktop())

    def test_secure_guard_fails_closed_when_security_state_is_unavailable(self):
        diagnostics = loadDiagnostics()
        with mock.patch.object(diagnostics.sys, "modules", {}):
            self.assertTrue(diagnostics.isSecureDesktop())


if __name__ == "__main__":
    unittest.main()
