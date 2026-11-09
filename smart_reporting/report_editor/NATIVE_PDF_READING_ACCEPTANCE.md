# PDF reading-position restoration acceptance

2026-11-09. Bounded native reading continuation in PR #196; not full View parity.

## Original material and implementation

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:
`apps/pdf/src/renderer/view-state.ts` is copied byte-for-byte as
`genoffice-pdf-reading-state.ts` (SHA256
`22b1435074f5f435d6ac30fd3fa533b16cd61cc5ca413b1c1a32338d54899c18`).
App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d` supplies the open,
two-frame restore, 300ms debounce and pagehide lifecycle. Original files and
hashes/adaptations are recorded by `genoffice-pdf-reading-source.json`.

Reuse source sanitization, fractional position, optional fit mode, best-effort
storage and100-entry least-recently-saved pruning. Native path identity becomes
scope(database/company/user/thread)+document+revision+source SHA; it cannot reuse
another user's/document's/revision's record. The map remains under the source
VIEW_STATE_KEY; each native entry has an explicit versioned identity prefix.
Numeric page is the original source page number inside that immutable snapshot,
not mutable display order. DOM rows account for native headings/notes, responsive
gaps and spreads. Deleted targets fall back to the first surviving row at its top.

Custom zoom restores within0.1–8; fit width/page recalculates using the existing
native current-page fit implementation on reopen. This does not claim the desktop
whole-row/whole-document fit or continuous resize behavior. Restoration waits two
animation frames while persistence is blocked, and explicit user input/navigation,
zoom anchors, search and comment targets take priority. Refresh retains the read
fraction without changing the selected page; initial reopen/preview return may
select the restored row. Source and actual preview positions are separate: preview
scroll/zoom cannot write the source record, and return restores the source snapshot.
Document-transition readiness, generation/disposal guards and listener/timer cleanup
prevent late writes. Pagehide and disposal flush before debounce expiry. Storage
parse/access/quota errors remain nonfatal; readonly revisions can remember position.
No HTTP, native operation, write protocol, dependency or file-format change.

## Tests and independent evidence

- Seven new targeted tests cover all scope/identity fields, malformed and blocked
  storage,100-entry pruning, source identity through reordering, fractional geometry
  after resize, spread grouping/right-page targets, deleted/empty layouts. Seven
  affected zoom/anchor/View checks pass. Repeated runs are not additional cases.
- Production-static Chromium154.0.8037.57 restores page2 at fractional position
  about0.36946 and scale1.5. Injected delayed animation frames plus a scroll event
  prove initial rendering cannot overwrite the record. Reopen after resizing retains
  the fraction; fit width recalculates from about1.93913 to1.50435 at a narrower
  viewport. Reverse/reload retains original page1, not display page1.
- Actual packed-engine preview contains an explicit reordered-page/new-note draft.
  Preview scrolling preserves the source record and return restores it. A real
  pagehide tears down the editor and flushes about0.42036 before300ms; readonly
  reload restores it. Other-user/same-file, other-revision/same-file, malformed
  entry and unavailable storage remain isolated and viewable. User navigation wins
  delayed restore. Selecting page2 while the viewport starts on page1 then zooming
  preserves selected page2. Reading actions add no draft operations.
- Four affected browser scenarios pass: View/night/zoom/print (original Ctrl-wheel
  content anchor assertion retained), occurrence search and actual-preview mapping,
  comments/history/delayed preview, and attachment download/failure retry.
- Independent pypdf verifies downloaded source is byte-identical. Actual preview
  order2,1,0 preserves all content streams/text/boxes/rotation/UserUnit, form values/
  widget appearances and original notes, and contains the explicitly added note.
  Draft contains only explicit reorderPages/addTextAnnotation, no reading operations.
- Final Standard57.08s/Slides58.03s builds, configured Standard budget, source SHA,
  smoke syntax and diff checks pass. Backend/runtime unchanged; older Node22 results
  are not counted as new checks. No whole suite repeated.

Source/download SHA256: `63e16912f76afb16c7fd6f32cc53a47645b7f9170aabe222602d1c27b89c9610`.
Actual preview SHA256: `ff5fce58ccc9cc24b68c1c71ff526bee141dfe094fa25011be0d35df09e41441`.
Evidence: `/workspace/scratch/pr196-pdf-reading-evidence.zip`.

## Failures and limits retained

Initial fixture fixes add a user wheel intent before scripted scrolling, tolerate
an unloaded viewport, await a distant note target's pointer handler, distinguish
source LRU timestamp flush from a changed reading state, and reserve synthetic
pagehide for actual teardown/reload rather than continuing to use a disposed view.
An actual View regression exposed reading restoration overwriting the Ctrl-wheel
anchor; explicit zoom ownership fixes it and the original browser assertion passes.
Review also separated selection restoration from scroll preservation and blocked
source persistence during preview document transitions. Raw failures remain archived.

Budget wording is corrected: check-build-budget.mjs only inspects static/assets.
Earlier budget-slides-named logs reran the Standard budget; they do not establish a
Slides-specific budget. Slides production build passes, without a configured equal
budget claim. Previous comments/attachments documents are corrected accordingly.
Browser auth/revision routes are substitutes, not production SQL/auth acceptance.
Desktop, full image, deployed identity/network, full keyboard/layout/fit semantics,
comparison, reply and attachment mutation, and whole PDF parity remain open. Flags off.


2026-11-09 row-fit follow-up: `NATIVE_PDF_FIT_ACCEPTANCE.md` supersedes the
previous active-page-only fit and missing continuous resize checkpoint. All
retained single/paired canvases now constrain fit; native fixed chrome differs
from the desktop side-note margin/full host layout. Earlier stage evidence/counts
remain historical and are not recounted as new checks.
