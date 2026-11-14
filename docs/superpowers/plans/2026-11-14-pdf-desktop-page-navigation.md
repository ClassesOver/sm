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
