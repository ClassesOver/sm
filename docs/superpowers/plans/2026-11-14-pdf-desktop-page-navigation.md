# PDF desktop reading navigation

## Scope and source audit

- Baseline: `680edfa` (integrated harness/revision-event branch).
- Existing four-format AI inventory is `smart_reporting/report_editor/NATIVE_AI_SOURCE_TOOL_COVERAGE_20261113.md`, with frontend boundaries in `NATIVE_AI_ASSISTANT_FRONTEND_ALIGNMENT.md`, not a newly inferred list of completed tools.
- Source inspection found the PDF viewport already focusable, page-number input and `jumpToPageForIdentity` already functional, but no PageUp/PageDown reading keyboard route.
- No Superpowers skill was exposed in this executor's skill catalog or found in checkout `.agents` / local skills inspection. This file follows the existing planning location without claiming a skill was run.
- Astra reviewed this as an independent **non-AI** PC interaction slice. It does not close PDF `goto_page`, Codex integration, or four-format AI parity.

## Implementation

Use PageUp/PageDown and Home/End only when the reading viewport itself has focus. Reuse the current visible `state()` order, page identities and existing navigation/update-controls/render-text-panel path. Preserve sm styling and focus; do not add controls, branding, network calls, saves or document mutations.

Ignore descendant controls, modifiers, composition, consumed events, open modals and active pointer gestures. Enable only select/reading mode after loading and outside preview, printing, saving, pending mutation or unstaged text. Read-only documents are not excluded by editing permission. Abort the binding with the editor's existing AbortController.

## Verification

- `git diff --check`: passed.
- Node 24 built-in TypeScript stripping / EventTarget smoke: passed navigation, non-wrapping boundaries, reordered page IDs, composition/modifier rejection, pointer gesture and disposal. This is not browser DOM verification.
- Added focused Vitest DOM coverage: boundaries, order changes, removed/empty pages, child controls, modifiers/IME, consumed events, availability, native/custom modals, pointer cancellation, focus retention, disposal/remount, unrelated keys.
- Vitest and TypeScript build: **not run here**, because this executor lacks project node_modules. No dependencies were installed. Must run in configured sm cloud environment before acceptance.
- Real browser focus/navigation and PDF regression tests: **pending** in the same configured environment. No PR/push/merge/deployment performed.

## Astra review corrections

- Navigation now derives its current reading page from the existing `capturePdfReading` DOM anchor using current `state()` page IDs. It no longer uses stale selection `activeId` after wheel scrolling. In two-page spread mode, this follows the existing reading-state row anchor (left page), not a new selection state.
- At first/last-page PageUp/PageDown, consume the key without invoking navigation, preserving the current within-page scroll offset. Home/End remain explicit page-top jumps.
- Disable shortcuts during `searchRendering`, which can temporarily detach/rebuild page rows. Unmeasurable layouts provide no reading anchor and do not navigate.
- Added DOM geometry regression for stale selection versus scroll position, reordered/blank identities and last-page offset preservation. Revised Node smoke passed. Vitest, TypeScript and real browser checks remain pending; this change is not accepted as browser-verified.
- In two-page spread mode, PageUp/PageDown advances by the actual DOM reading row using existing `pdfReadingRows`, not a fixed two-page stride. This prevents repeatedly targeting the right page of the same row when the captured reading anchor is its left page. Home/End remain first/last page jumps; a final complete or partial spread does not wrap or reset its offset. Added DOM geometry regression cases for complete/odd-tail spreads and responsive single-column rows.

## Real-browser rejection and follow-up repair

Independent real `createPdfEditorView + PDF.js` acceptance rejected `79e9076`: rapid PageDown (45–49ms spacing) repeatedly chose page 2 because smooth scrolling lagged behind the keys; at 50% zoom, End selected page 5 but physical bottom clamping left the captured reading anchor on page 4, so PageUp skipped to page 3. These failures supersede earlier smoke success; the prior change was not accepted.

Following Astra review, keyboard navigation uses instant scrolling and a small interruptible navigation intent (target page identity, not another document selection). Repeated keys advance from that target even when geometry cannot align a short final page. Existing page-number, thumbnail, outline, search and comment navigation record their explicit target; End's right-page identity maps into its actual reading row. Wheel/pointer/touch, losing canvas focus, blur, refresh and layout/scale/page-order changes invalidate the intent; ordinary programmatic scroll events do not. With no intent, physical bottom of a scrollable document recognizes its final reading row. A fully visible document does not infer a bottom-only target.

Node rapid-key/explicit-tail intent smoke and diff-check passed. Added regression tests for rapid keys with lagging geometry, explicit short-tail target, right-page spread End, and intent invalidation. Vitest/TypeScript and renewed independent real-browser acceptance remain pending. No PR has been opened.
- Final Astra code review identified native keyboard scrolling as another user interruption: viewport keys not owned by this helper (including Arrow keys, Space and modified navigation) now clear intent without consuming the event. Added native-scroll interruption regression. Review allows submission for independent cloud verification, not acceptance approval.
