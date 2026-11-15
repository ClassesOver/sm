# PDF all-page row fit and continuous reflow acceptance

2026-11-09; bounded continuation in PR #196, not whole desktop/View parity.

## Original material and implementation

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`: App.tsx
blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d` rowSize/recomputeFit/
ResizeObserver/row rendering, `spread.ts` and `view-config.ts`. The complete pure
spread module is copied unchanged (SHA256
`2a14a364c2fb3b38ef2e4509260ee4bccc55e8f471716c5a4d133186f167cfde`).
Original files/hashes and native adaptations are in
`genoffice-pdf-fit-source.json` and the evidence archive.

The previous native fit used only the selected page. A selected100-wide page could
choose8x while a900-wide page overflowed. The previous shared two-column grid also
combined column maxima from different rows: pairs900+100 and100+900 need1036px
including16px gap/two10px borders, but shared grid tracks need1836px at1x. The
archive retains the committed baseline excerpt and explicitly labeled static
arithmetic counterexamples; these are not claimed as executed baseline browsers.

Fit now constrains every surviving canvas in current original-page order. Adjacent
pages form independent flex rows using unchanged source pairing. Width fit finds
the limiting row; page fit also constrains every page height. Native borders,
headings and16px gutters stay unscaled; responsive viewport padding is measured.
Effective crop/rotation is used in source view, actual PDF bounds in output preview.
Note cards remain below the pages and wrap to their canvas width. Fit targets the
canvas plus heading chrome, not expanded notes; desktop300px side-note margin
layout remains different. Pinned0.1–8 limits remain, so extreme windows/documents
may overflow at the minimum rather than falsely promise unlimited fitting.

ResizeObserver/window resize coalesce work into animation frames. Reflow defers
through rendering/preview/printing, resumes afterwards and cancels on disposal.
The zoom selector retains only fixed steps plus its current custom ratio.
Manual zoom cancels fit and stale restoration requests; explicit fit buttons also
replace obsolete mode requests. Selected page, content anchors and explicit search/
comment navigation retain priority. Unchanged form model/value operations reuse
controls so reflow preserves uncommitted input/focus without creating edits. No
server API, write schema, dependency or engine change.

## Acceptance

- Seven new helper cases cover all-page limits, independent visible pairs/odd tail,
  fixed chrome at fractional zoom, resized/rotated display bounds, hidden/invalid
  geometry, pinned scale limits and150,000 pages without argument-spread overflow.
  Twelve affected reading/zoom cases pass;19 total, without recounting reruns.
- Production-static Chromium154.0.8037.57 uses a five-page fixture with alternating
  wide/narrow pages, odd tall tail, original notes and real form fields. Independent
  DOM bounds prove all row widths fit; page mode also fits all canvases plus headings,
  with a limiting bound tight within1.5px after stable frames. Results include single/
  paired layout, window width/height changes, sidebar close/comments, manual zoom
  stopping adaptation, reopen fit, rotation/deletion, actual preview/resizing/return,
  readonly/mobile and queued resize followed by pagehide teardown.
- Selecting the narrow page leaves selection intact. Uncommitted contact text and
  focus survive automatic resizing with no draft operation; blur commits and undo
  restores it. Final draft has only explicit note/rotation/delete plus deletion's
  existing normalized-order record. Deleting the tallest page increases fit scale
  from about0.27786 to0.46267.
- Five affected browser scenarios pass: View/Ctrl-wheel/print, reading restoration,
  occurrence search, comments and attachment read/export. Existing fault/read-count
  assertions are retained with deterministic release gates rather than150ms races.
- Independent pypdf verifies source/download byte equality and actual preview pages
  original0,1,2,3, only original page1 rotated90°, original content/text/boxes/UserUnit,
  field values/widget AP and original notes preserved. New note exists; transient
  form text is absent from the saved field value. No view-only operation was added.
- Final Standard58.37s/Slides59.10s builds, configured Standard budget, primary/local
  source hashes, smoke syntax and diff pass. Slides has no equivalent configured
  budget. Backend unchanged; earlier Node22 checks are not counted anew. No full
  suite repeated.

Source/download SHA256: `2984fcc160d2172fbc65aac535f98d7e189ba949123a973aec2fb256cbff52e5`.
Actual preview SHA256: `e6e5b8019d9e8590e4da1200cc7d259ce5ed2ceb3154970f984c63a46e3f41a5`.
Evidence: `/workspace/scratch/pr196-pdf-fit-evidence.zip`.

## Failures and boundaries

Browser testing exposed an actual stale-fit/manual-zoom race; explicit zoom/fit
requests now cancel old reading restoration, retaining the original assertion.
Review identified form-input loss during automatic full refresh; unchanged form
controls are now reused and browser focus/value/undo plus file readback verify it.
Fixture corrections select visible Home/fillForm tabs, target the first actual page
instead of every row's first child, wait for completed preview controls/note-mode reflow, and expect
existing delete normalization. Annotation/attachment faults are released after close
rather than racing a150ms timer. Independent readback compares numeric PDF geometry
semantically (0.0 equals0), while still comparing streams/dictionaries independently.
Raw failures are retained, not counted as passing/new cases.

Browser auth/revision routes substitute persistence; no deployed SQL/auth claim.
Desktop side-note margin/full host layout, sidebar width persistence, full shortcuts,
comparison, reply/attachment mutation, remaining PDF families, full image and
production identity/network remain open. Flags remain off; no merge/deploy.


2026-11-09 sidebar follow-up: `NATIVE_PDF_SIDEBAR_ACCEPTANCE.md` supersedes the
missing shared sidebar sizing/persistence checkpoint. It also covers thumbnail
raster lifetime and stable-position/latest-fit pagehide handling during reflow.
Earlier stage evidence remains historical; full desktop context/layout is open.
