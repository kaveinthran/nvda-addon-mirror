# Installed add-on diagnostics — manual acceptance

This feature is local to NVDA. It does not upload logs, download packages, remove add-ons, or restart NVDA.

1. Install the combined test candidate and restart NVDA. Open **Tools > Installed add-on diagnostics**. Verify that the checklist has a useful accessible name, each item announces its configured enabled or disabled state, and Tab reaches the checklist, evidence viewer, log-evidence button, and buttons in order.
2. Select an add-on with a known global plugin or driver. Verify that the read-only viewer calls the module list **loaded-module evidence** and says that it is not an activity claim. Select an add-on without loaded code and verify that the absence statement does not claim it is inactive.
3. Activate **View related current-session log evidence**. Verify that NVDA remains responsive while the log is read, only short related lines appear, and the viewer says that a log reference does not prove activity. In a new session whose tail does not include an identifiable “Starting NVDA” boundary, verify that no older-session lines are shown.
4. Check one ordinary configured-enabled add-on. Activate **Disable checked add-ons** and verify that the confirmation names exactly that add-on, says the change takes effect after restart, says files are not removed, and does not restart NVDA. Cancel first; then, if you intentionally want to test the pending-disable path, confirm and verify it in NVDA's Add-ons dialog before restarting. Re-enable it through the normal Add-ons dialog after the test if needed.
5. Use the all-enabled defaults only with add-ons you are prepared to disable on restart. Verify the helper itself is not checked by default; it may be included only by deliberately checking it. Verify no action starts until confirmation.
6. On the secure desktop, the menu action must fail closed and must not show installed add-on information.

Record NVDA version, whether speech and braille announced state correctly, keyboard/focus results, and any log or restart behaviour. Automated tests do not provide this live evidence.
