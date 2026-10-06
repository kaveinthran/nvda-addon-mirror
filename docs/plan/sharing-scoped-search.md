# Sharing and scoped search (F1)

## Outcome and boundaries
Let a user copy selected add-on information/download links and choose which field a search matches. Retain the existing store, source-aware search, ordering, channel/compatibility filters, deferred-search setting and batch menu. No network access, source routing changes, saved browsing state, new gestures or automatic installation in this family.

## Requirements and design
Share copies the available display name, description and authoritative sourceURL, with homepage fallback. Copy download link uses the selected store model's URL and is unavailable for missing/unsafe metadata; installed manifest-only entries never fabricate download links. Plain text preserves Unicode and signed URLs. Reject non-HTTP(S) schemes, credentials, literal whitespace/control characters, invalid ports and missing hosts. Clipboard success/failure uses a single short message.

Search field offers All text, Title, Author or publisher, Description, Add-on ID and Source. All text delegates unchanged. Scoped matching intersects the original ordered search result with exact case-folded field matches; it does not mutate core's query, sort or model collection. Changing the field deliberately applies pending text, including in deferred mode. Typed text still follows the existing search/Enter setting.

Adapt core's persistent AddonActionVM creation, AddonListVM filtering and the dialog's labelled-control builder. Core owns action targets and keyboard context menus, including single/batch selection. Register patches through the existing list; capture its length and roll back only the new suffix on failure with ownership checks. New entry points do nothing on secure desktop or if secure-state detection is unavailable. No worker/thread is introduced.

## Tasks and evidence
1. Inspect 1.4.4 source/tests and supported core API generations. Baseline 332 tests passed.
2. Independent plan review. Adopt action-model integration and ordered-result intersection; keep prior-feature patches on failure.
3. Add URL/share/scope helpers and native actions/choice. Preserve authored indentation and translation conventions.
4. Add focused regressions for Unicode, URL fallback/rejection, field isolation, core ordering/selection, explicit deferred application, clipboard errors, secure guard and partial rollback.
5. Run warnings-as-errors suite, style supplement, diff check and package/source identity verification.
6. Independently review code and resolve actionable blockers before pushing a draft PR.
7. Build a named experimental package and follow the [manual test guide](../testing/sharing-scoped-search.md). Record actual speech, braille, keyboard, focus and supported-version results before marking release readiness.

## Compatibility and maintenance
Keep upstream minimumNVDAVersion 2025.1 and lastTestedNVDAVersion 2027.1; preserving declarations does not assert live testing. Inspected official release-2025.1 source and current-development source, plus a supplied local clean NVDA checkout at 4dd8aec18f27b4c583180fda235fd596cef74de0. The adapter must not replace the data-manager singleton. Source support remains installed before scoped filtering so Source matches retain provenance behavior on both API generations.

Development version 1.4.5-dev2 is a local test identity, subject to maintainer version choice before merge. A draft PR and passing unit tests do not prove live NVDA acceptance. Public releases, Store submission and workflow modifications remain outside this change.
