# PDF browser host

## Ribbon migration status

The original ribbon command surface is defined inline in GenOffice's
`apps/pdf/src/renderer/App.tsx` at pinned commit
`f8c17004fb730df11f0f743164ffd8b4281bb38c`. The React App cannot be imported as
a browser-safe ribbon module: it owns PDF document state and directly couples
the tabs to desktop file dialogs, Electron printing, native paths, and local
certificate signing. `pdf-ribbon.ts` keeps the upstream tab IDs and contextual
Fill Form/Form Design tabs while the current PDF view supplies its own command
groups. Existing download, undo/redo, search, zoom, highlight, sticky note,
page rotation/reorder/delete, and gated original-text replacement are connected
to the native editor. Fill Form reads actual source AcroForm fields and stages
source-bound text, checkbox, radio and single-dropdown values. Other command
families remain visibly disabled with their missing writeback or security
boundary stated on each control. The Form Design tab remains disabled because
the existing widget writer can fall back from a missing widget identity and
skip invalid edits without a verifiable receipt.

The Pages tab preserves the source control order in four groups: rotation;
delete/extract/insert/replace; crop/page size; reverse/split/merge. Its semantic
IDs use the local `genoffice.pdf.page.*` namespace because the source has no
stable DOM command IDs. Left/right rotation, delete, extract, import, replace,
crop, sizing, reverse, split and merge actions are individually mapped. Left/right rotation, clockwise rotate-all, delete, insert blank page, and reverse have verified
bridge operation paths; the other
source actions stay disabled with their own bridge or publication reason. The
local move-previous/move-next controls remain in a separate draft-controls
group and are not presented as source commands. The four-group command ledger
and capability boundary are tested in `pdf-page-ribbon.test.ts`. View keeps the
source navigation and page-zoom groups: thumbnails, outline, search, page jump,
single/two-page layout, zoom and fit controls work. The outline resolves named
and explicit PDF.js destinations to immutable source page indexes; external
URLs are never followed. Home and View page inputs share one page-order state,
and zoom controls share one PDF.js scale. Night mode remains disabled with its
specific reason. A two-page Chromium save smoke resolves a real PDF outline,
navigates to page 2, toggles spread layout, zooms out, returns through the Home
page input, then saves/downloads and reads back the original AcroForm values.

Fill Form also provides the source previous/next field commands. They focus
enabled field controls in document order with wraparound, and are disabled
when no editable fields exist. Browser save/download/reopen smoke covers both
directions before changing and independently reading back supported field
values. Home groups follow source order (AI, Markup, Edit, Convert & Export,
Page & Zoom, Search/Print/Properties); Annotate groups follow AI Review, Markup,
Draw Tools, and Signature & Protection. Unsupported Home/Annotate actions carry
fixed-source semantic IDs in `data-source-command-id` and individual capability
reasons. The source has no stable DOM command ID contract, so these IDs identify
the pinned action semantics locally.

The host uses a browser-safe subset of the pinned source icons, color presets
and English/Simplified Chinese ribbon labels. The 12 markup presets are grouped
under Markup Color and expose their selected state; choosing a custom color
clears preset selection. View exposes Fit Width and Fit Page calculated from
the active source page dimensions and PDF viewport bounds. Full command
order/coverage and the React `ColorPickerPopover` are not ported. Desktop App
state and Electron dependencies remain excluded.

The seven source tabs and contextual command groups were inventoried in
`NATIVE_RIBBON_DESIGN.md`. Digital certificate signing remains unavailable
until a separate key-custody design is reviewed. Browser Print renders every
saved source page into a temporary host before calling `window.print()`. It is
disabled while the document is dirty, locked or in preview. Print CSS hides
shell chrome and paginates the PDF canvases. The Playwright mock-print smoke
verifies page order, all-page rendering, media CSS visibility and afterprint
cleanup; it does not certify PDF.js rendering to a physical printer.

The PDF view uses the same PDF.js 6.2.108 legacy canvas/TextLayer renderer as
GenOffice `apps/pdf/src/renderer/PdfPage.tsx` at commit
`f8c17004fb730df11f0f743164ffd8b4281bb38c` (Apache-2.0). Its page bitmap budget
and device-pixel-ratio cap follow that upstream renderer. The host is local
code; desktop IPC, menus and original-text editing are not imported.

`pdf-main.ts` renders the actual immutable PDF bytes and PDF.js selectable text
layer, thumbnails, search, saved note contents and draft overlays. PDF.js
PageViewport provides the forward/inverse coordinate transformation, including
CropBox origin, UserUnit, zoom and all right-angle rotations. `pdf-operations.ts`
retains source page IDs across deletion/reordering; display indices never
replace source identities. NativeDraft owns undo/redo, snapshot binding and save
locking; native-session owns publication UI and switching revisions.

The baseline supports highlight, sticky-note comments (fixed 20x18 PDF units),
rotation, deletion and reordering. Native text replacement is separately gated
as described below. Deleting a page also discards its draft
annotations/rotation; undo restores the full prior operation snapshot. Saved
annotations remain part of the PDF page canvas; saved Text comments are also
listed under that page. OCR is unavailable; content-stream text replacement has the narrower Task 9 contract below.

PDF.js worker is emitted by Vite's `?url` import. Its cmaps/standard_fonts/wasm
assets must be served under `/reports/v1/editor/assets/pdfjs/`; the application
build copies these from the pinned npm dependency. Their upstream license must
remain with the distribution. See the application build configuration.

Validation evidence (2026-11-05): seven operation/coordinate unit cases pass.
A real Chromium session used actual NativeEditorService, signed native grant,
CSRF, NativePublicationService, PDF bridge and download service with an in-memory
revision repository fixture. A four-page PDF with nonzero CropBox and Rotate
0/90/180/270 rendered; highlight, Chinese sticky note, rotation and reordering
were previewed, saved, downloaded and reopened as a new revision. The expanded
probe also verified search, deletion with undo, saved note contents and the
closed prior revision. No browser page errors occurred. Twelve real PDF.js
viewport inverse cases covered all four rotations, scales 0.5/1/2, nonzero
CropBox and CSS scale 1.3. Targeted TypeScript checking passed. An independent
pypdf read verified the downloaded page order, rotation, CropBox, Highlight and
Chinese Text Contents. Desktop/mobile screenshots and the temporary fixture
are in `/tmp/pdf-native-web-smoke/`. This is not a deployment or full browser
compatibility matrix; feature flags remain off pending application acceptance.

Task 9 adds a separately gated native text replacement flow. `pdfTextEnabled`
must be true before the entry is shown or the extra source text-object inspect
request is issued. Only nonempty server-inspected source objects are selectable;
source IDs and expected exact text hashes are copied into `replaceText` draft
operations, with a 4000 UTF-16-unit input cap. Empty/unreadable physical objects
remain server evidence for overlap detection and are never offered as targets.
Scanning/empty pages explicitly state that OCR editing is unavailable. A failed
text census disables this entry while retaining basic viewing and annotations.

Text edits render as actual output bytes only after preview. The client obtains
the full-draft JSON receipt, passes its `previewDigest` to `previewFile`, whose
server and HTTP client verify the digest, then loads the returned PDF through
PDF.js. All draft page/annotation/text changes are present in that actual canvas
and selectable text layer. Source text-object identities remain in a separate
immutable model; output page identities are never reused as edit anchors.
Coordinate editing is disabled during actual preview. Returning to the original
allows further editing and clears the review confirmation.

The review lists every applied/skipped operation, states that skipped text kept
its original content, and requires an unchecked checkbox followed by another
save. `prepareSave()` supplies `confirmedPreviewDigest` to the shared session
only after explicit review. `PdfPreviewReview` binds that confirmation to the
entire serialized operation snapshot, and any edit followed by undo still loses
the prior review. Pending textarea input must be added to the draft before
preview/save. The source text is not visually replaced by a DOM overlay.

Additional verification (2026-11-05): the two new operation/review unit cases
failed first and then passed (nine total targeted PDF operation cases). A real
Chromium session through the actual application bootstrap, native grant, CSRF,
NativeEditorService, JSON preview, preview.pdf, NativePublicationService and
actual download completed Chinese replacement plus an overflowing text skip.
The first save made no save request, the checkbox started unchecked, returning
to source and undoing invalidated the confirmation, and the final save carried
one explicit digest before opening the new revision. A second session confirmed
and saved with the skip retained: it displayed the specific skip warning and
still received a usable PDF download. Both sessions had no page errors. Actual
pypdf readback verified Chinese page-content text, removed old source text,
retained control text, four pages and no added annotation. A flag-off session
rendered the PDF without a text entry or any extra text-inspection request.
Desktop/mobile screenshots and fixture scripts are under
`/tmp/pdf-text-native-web-smoke/`; independent engine text/PNG checks and the
resource-bound digest contract are documented in the PDF engine SOURCE.md.


2026-11-06 bounded Page rotation continuation: `page.rotateAll` now follows
pinned App.tsx `rotateAllPages(90)` over `visList`. The host appends one source-
bound `rotatePage` +90 record per surviving page in one NativeDraft snapshot,
without changing page order, prior rotations, annotations or field values. A
500-record budget is checked before state changes, with a visible unavailable
reason if exceeded. Existing edit/preview/print/save/readonly locks apply and
text-preview approval is invalidated by the changed complete snapshot. Source
provenance and actual evidence are in `NATIVE_PDF_ROTATE_ALL_ACCEPTANCE.md`;
this does not close Task 5 or implement other page operations.


Whole-document comments (2026-11-09): pinned `note-threads.ts`/`CommentsPanel.tsx`
read semantics and unmodified extracted date parser have upstream/local hashes in
`genoffice-pdf-comments-source.json`. Native changes use iterative malformed-thread
handling, immutable sourceRef joins, per-document cache/error retry and existing
saved/pending card navigation instead of source popovers. Text-note replies are
readonly; no reply write contract. See `NATIVE_PDF_COMMENTS_ACCEPTANCE.md`.


Attachment reading/export (2026-11-09): pinned AttachmentsPanel/App originals and
hashes are recorded by `genoffice-pdf-attachments-source.json`; humanBytes is
unchanged. Native adaptation keeps internal PDF.js6 Map keys distinct from display
filenames, document promise caches/retry and lifecycle guards. Browser Blob
export replaces Electron's dialog; already-authorized opened-PDF bytes need no
new backend route. Attachment add/remove is not implemented. Evidence:
`NATIVE_PDF_ATTACHMENTS_ACCEPTANCE.md`.


Reading persistence (2026-11-09): view-state.ts is copied unchanged with SHA in
`genoffice-pdf-reading-source.json`; source App open/restore/300ms/pagehide lifecycle
is the primary reference. Native adaptation scopes keys to immutable authorized
identity and measures DOM rows instead of assuming desktop row heights. Numeric
page retains original source ordinal, not mutable output order; preview view state
never overwrites source. Existing basic fit recalculates on reopen, not full source
fit/continuous resize parity. See `NATIVE_PDF_READING_ACCEPTANCE.md`.


All-row fit/continuous reflow (2026-11-09): unchanged pinned spread.ts supplies
adjacent visible-page pairing; App rowSize/recomputeFit/ResizeObserver and fixed
PAGE_GAP are primary references. Native fit uses actual responsive padding and
unscaled heading/border/gutter constraints across all retained canvases. Notes
stay below pages instead of the source side margin. Form controls reuse unchanged
model/value state during automatic reflow. Provenance/adaptations:
`genoffice-pdf-fit-source.json`; evidence: `NATIVE_PDF_FIT_ACCEPTANCE.md`.


Sidebar sizing (2026-11-09): unchanged sidebar config extraction and App drag/
thumbRasterW/window clamp are recorded in `genoffice-pdf-sidebar-source.json`.
Native adaptations add nonfatal storage, ARIA keyboard/cancellation cleanup,
measured pane chrome, DPR2 raster caps and document/page lazy bitmap lifetime.
Initial/preview reading guards stay intact while pagehide during ordinary reflow
saves stable position/latest fit intent. See `NATIVE_PDF_SIDEBAR_ACCEPTANCE.md`.

Calibrated measurement continuation (2026-11-09): unchanged pinned
`apps/pdf/src/renderer/measure.ts` supplies calibration and two-decimal labels;
`MeasureScaleDialog`/App first-reference, cancellation and recalibration semantics
are adapted to the native dialog and immutable page/draft scope. Measurements use
the existing engine's Line/AP/Helvetica writer. The adapter limits units/labels to
printable ASCII and finite representable scales because that fixed writer embeds
Helvetica text directly. Session calibration is not persisted; committed labels
are immutable draft data. See `NATIVE_PPTX_PDF_NEXT_ACCEPTANCE.md` for provenance,
independent file checks and the remaining source differences.
