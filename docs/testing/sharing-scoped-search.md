# Sharing and scoped search: development candidate test guide

Candidate: `addonStoreMirror-1.4.5-dev2.nvda-addon`. This tests family F1 only. Author discovery, cloning, saved filters/columns, update-source settings, changelog history and running-add-on diagnostics remain planned separately.

## Record the environment
Record Windows version, exact NVDA version/build, portable or installed mode, helper version, NVDA language, braille display if used, other store-related add-ons and Search while typing setting. Record the package SHA-256 from its accompanying verification record. Do not submit private full logs; a short relevant error with private paths removed is sufficient.

Use a test NVDA configuration or portable copy. Back up settings before replacing an existing helper. Install this local candidate through NVDA's normal add-on installation interface and accept/restart only when you choose to do so. Confirm helper version 1.4.5-dev2 in Installed add-ons. The package retains upstream compatibility declarations (2025.1 minimum, 2027.1 last-tested); these declarations are not evidence of this candidate having been live-tested.

## 1. Controls and focus
1. Open NVDA menu > Tools > Add-on Store > the regular Add-on Store.
2. After the catalog loads, use Tab and Shift+Tab through the controls.
3. Find Search field. Expected: a named choice control with value All text. Its choices are All text, Title, Author or publisher, Description, Add-on ID and Source.
4. Change the choice with arrow keys. Expected: no unexpected move to another control and no activation of an Install action.
5. Record actual spoken name, role and value, and actual braille output separately. If no braille display is available, mark braille Not checked.

## 2. Share details
1. In Available, select exactly one add-on whose source page you recognize.
2. Press Applications or Shift+F10. Expected: existing actions remain, plus Share add-on details and Copy download link when release metadata provides a usable URL.
3. Choose Share add-on details using arrows and Enter. Expected: one short 'Copied to clipboard' announcement, also available to braille; focus returns to the selected store item.
4. Paste into a plain text editor. Expected: the displayed name, description and source page URL separated by blank lines. It uses the source page when provided, otherwise the homepage; a non-GitHub source is kept as its real URL.
5. Repeat using Enter on the list item to open its actions. Expected: the same sharing command works.
6. Select a different add-on and repeat. Expected: the new item's text, with no duplicate or stale menu entries. Repeat opening/closing the menu at least five times.
7. Close a menu with Escape. Expected: focus returns to the same row, without installation.

## 3. Direct download link and missing metadata
1. Select an Available entry with an identifiable release and choose Copy download link.
2. Paste into a text editor. Expected: the package URL for that selected release/channel, not the source repository/homepage and not a rewritten mirror URL. Query strings remain intact.
3. Compare against the selected version and channel. Copying itself should not start a download or open a browser.
4. In Installed, test an add-on installed manually that has no store cache. Expected: sharing can still copy its name/description/homepage; Copy download link is absent if no download URL exists. A missing URL is never guessed from the homepage.
5. Select several rows. Expected: the existing batch actions remain. The two single-add-on copy actions are not offered on the batch menu.
6. Apply a search with no results. Expected: no valid sharing/download actions on an empty selection.

## 4. Search scope
Choose real terms you can verify in the displayed details. Test exact substrings first; scoped search deliberately narrows broad results to case-insensitive field matches.

1. All text: search an ordinary add-on name and an upstream source label. Expected: existing broad search behavior remains.
2. Title: use a term found only in one add-on's description. Expected: that add-on is excluded; a term in its displayed title includes it.
3. Author or publisher: use an author's/publisher's name. Expected: matching catalog publisher or installed manifest author is included; description-only matches are excluded.
4. Description: use a description term. Expected: title-only matches without that term in the description are excluded.
5. Add-on ID: use the internal manifest ID from a known add-on. Expected: matching IDs, without unrelated description matches.
6. Source: use part of the Source column's label. Expected: matching provenance labels only. Installed add-ons without source metadata may not match.
7. Try mixed-case and a non-ASCII author/title if available. Expected: case-insensitive matches and intact Unicode in copied text.
8. Clear the search. Expected: all entries allowed by the existing channel/status/compatibility controls return in their normal ordering.
9. Change sort, channel and compatibility controls. Expected: scope does not bring back entries excluded by those controls. On current NVDA, relevance order remains core's order among the scoped matches.

## 5. Deferred search
1. In Preferences > Settings > SerrebiRadio add-on store, uncheck Search while typing, save, then reopen the store.
2. Set Title, type a known title term. Expected: typing alone does not change the list.
3. Press Enter while Search has focus. Expected: the search is applied without activating the default button.
4. Clear it and press numpad Enter. Expected: the list returns to unfiltered contents.
5. Type pending text, then deliberately change Search field to Author or publisher. Expected: this explicit choice applies the pending text to the newly chosen field even though ordinary typing remains deferred.
6. Re-enable Search while typing and repeat a scope search. Expected: results update while typing.

## 6. Tabs, official store and cleanup
1. With a specific scope selected, switch tabs. Expected: scope stays selected for this dialog; the existing tab behavior resets the search text. Saving filters and scope across reopen is not implemented in F1.
2. Close and reopen the store. Expected: Search field defaults to All text, with no duplicate controls/actions.
3. Open Tools > Add-on Store > Official NVDA store. Test title search and sharing. Expected: safe available metadata works; Source may be empty because the official store does not provide the mirror's provenance field.
4. Close it with its Close button and reopen the regular store. Expected: the existing mirror restoration still works.
5. After saving your observations, disable the test helper using normal core UI and restart if prompted. Expected: core store has no added Search field control or sharing actions and the original store URL is restored.

## Results template
For each numbered section record Verified pass, Verified failure, or Not checked, with the exact NVDA version. For failures include the step, expected and actual speech, actual braille (or Not checked), focused control and whether the issue reproduces after reopening. Speech/keyboard/braille/secure desktop/minimum-version checks remain Not checked until observed in a real NVDA session.

Automated checks cover URL validation/fallback, Unicode, field isolation, core ordering, selection-target changes, deferred choice application, clipboard errors, secure-entry guards and patch rollback. They do not prove live speech, keyboard event delivery, braille output or package installation.
