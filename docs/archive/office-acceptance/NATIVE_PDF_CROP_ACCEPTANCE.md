# Native PDF current-page crop acceptance

2026-11-06. This closes the current-page crop command gap. It does not complete
Task 5, all-source ribbon parity or desktop acceptance.

The later `NATIVE_PDF_CROP_ALL_ACCEPTANCE.md` closes the all-surviving-pages
checkbox; counts and current-page evidence below remain the original checkpoint.

## Original material and chosen boundary

Read pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`, original
`apps/pdf/src/renderer/App.tsx`, Git blob
`e87bc4f85aadc77bcc9cfb152619c17b8c70a30d` (downloaded source retained in the
acceptance archive):

- Lines 6674–6707 render the current displayed page including rotation, interpret
  a fractional display-space crop, skip full-frame no-ops and map visible page
  position to its original target.
- Lines 11887–11903 provide the image crop dialog and optional all-pages checkbox.
- Vendored `src/main/save-pdf.ts:1373` implements `cropPagesBytes` by mapping the
  displayed region and calling pdf-lib `page.setCropBox`; MediaBox/content remain.

The native `genoffice.pdf.page.crop` command keeps its source group and identity.
It offers four percentage margins relative to the current displayed page, rather
than importing the desktop image dialog/IPC. Scope is the current page only;
image drag handles and the source all-pages option remain open.

The browser uses existing PDF.js inverse transforms, including CropBox offsets,
rotation and UserUnit, to store absolute unrotated bounds with the immutable
source page ID. Repeated crop commands validate against the current crop and
shrink further. Rotation never changes the coordinate identity. NativeDraft
provides one step per crop, Undo/Redo, refresh recovery and text-review snapshot
invalidation. Full-frame no-ops, empty/nonfinite/out-of-range margins, stale or
deleted targets, growth, sub-0.5-unit rectangles and the 500-operation limit are
guarded. An engine capability flag is required; old/unavailable engines stay
readonly for crop and preserve an unrecognized stored draft.

PDF.js viewport instances supply their own constructor for a draft CropBox
(PDF.js does not export that class); no new transform implementation is used.
Canvas, text layer, annotation overlays, thumbnails and fit controls use the same
viewport. The pinned PDF.js version is covered by real-browser checks below.

## Native writeback

The strict bridge accepts only `cropPage/pageId/rect` plus the existing optional
source digest. It validates the entire ordered list before writing, retains the
last validated bounds for each source page, and maps source indices through
final deletion/reordering. It uses the same pdf-lib CropBox setter as upstream,
after existing save operations, with `updateFieldAppearances:false`. No vendor
writer, serializer, desktop signing or arbitrary file access was added.

Crop only hides edge content. MediaBox, text streams, widgets and annotations
remain in the file, including objects outside the new visible region. The dialog
states this explicitly and says crop cannot remove sensitive information.
Invalid input has an alert inside the modal. Source bytes remain immutable.

## File and history evidence

`reporting/tests/test_pdf_crop.py` has **27 distinct new cases**:

- Eight combinations of rotation 0/90/180/270 and UserUnit 1/2 preserve MediaBox,
  rotation, UserUnit, all content streams/extractable text, serialized annotation
  and form dictionaries, outlines and untouched CropBoxes. Hidden text remains
  extractable, confirming that this is crop, not redaction. Old revision IDs fail.
- One composition case covers repeated crop, rotation, delete, reorder and an
  actual form value update with independent pypdf readback.
- Twelve malformed/out-of-bounds/small rectangle cases and six growth/conflict/
  identity/extra-field cases reject before returning a new output.

The first run passed 19 and stopped eight preservation cases at a reader-specific
IndirectObject comparison. The comparison was corrected to serialized PDF
objects (numeric references, not Python reader identity); all eight affected
cases passed. No writer change was needed for this correction. Logs are retained.
All **13 affected existing bridge file tests** also passed.

Frontend: **18 distinct new checks** pass across focused runs, plus the affected
Page inventory check and all **17 existing PDF operation/history/print/review
checks**. Initial history fixture lacked required scope; fixed. The invalid-array
table was corrected to pass arrays as single parameters after strict TypeScript
caught Vitest argument spreading, and its eleven rows were rerun. Budget/deleted
restore guards were rechecked after the final product change. Repeats are not
counted as extra cases. No full frontend/repository suite was repeated.

## Browser, HTTP and runtime evidence

`frontend/smoke/pdf-crop-smoke.mjs` runs against production static assets with
Chromium 154.0.8037.57 and the actual packed PDF bridge. Authentication/revision
routes are substitutes. Its four-page source has rotations 0/90/180/270, nonzero
CropBox offsets, UserUnit=2, text/checkbox/radio fields, outline and a note.

It verifies cancel/no-op/invalid modal input, then actual margins
left=10%, top=20%, right=30%, bottom=10% on all four pages. Width/height shrink to
60%/70% for every direction; for example 760×920 becomes 456×644, and 920×760
becomes 552×532. It checks Undo/Redo, genuine reload, another crop, subsequent
rotation, deletion/reorder, three form changes, save revision 2, download despite
validation failure, and new-revision reopen. Readonly forced dispatch cannot open
the dialog. Console/page errors are empty.

Independent pypdf checks downloaded pages correspond to original indices 3/1/0:

| Output | CropBox | Rotation |
| --- | --- | --- |
| 0 | [48,158,314,434] | 270 |
| 1 | [86,66,352,342] | 180 |
| 2 | [70.8,66,276,388] | 0 |

MediaBoxes/content streams/UserUnit and the note are preserved; contact=Ada,
consent=/Off, plan=/pro. Reopened first page is 552×532.
Final source SHA256:
`78711a9a2280f8a0bf66dc4b872ffb4858fb7d5877dbc81c51d6b91d9dde581a`.
Final download SHA256:
`6bca1965cb746ae51a0e91dbe556073e8f2c47b5643b7888aa96e590e666b3ea`.

The existing PDF ASGI combined scenario now includes crop+rotation+reverse.
**1 passed, 3 deselected** verifies upload/save/download/hash, failed validation
retaining links, immutable source, retry and revision reopen using actual file
engines. It remains in-process HTTP with memory repositories and synthetic
authorization. Initial collection lacked required test-only HMAC/public-base
configuration; supplying those fixtures resolved it without product changes.

Production-packed Node22, readonly/network-none: **2 passed, 25 deselected**
(270-degree UserUnit=2 preservation and the combination case).
Runtime CLI SHA256:
`21fef59085d8081a6380606c4db2fd61dadf779e5ce4d731181e8d093107f393`.
This is mounted-runtime proof, not a complete application image.

## Build and provenance

Final standard/Slides production builds pass (35.01s/39.62s), including frontend
strict TypeScript. Actual budget and budget contract pass. Ruff, smoke syntax and
diff checks pass; existing third-party chunk warnings remain.

A standalone strict bridge check retains six **pre-existing** diagnostics for
omitted desktop type-only packages and Electron resourcesPath. A baseline from
HEAD and the changed bridge produce identical diagnostics, zero new diagnostics;
this is not reported as a clean bridge tsc pass. The production bundle, actual
file checks and Node22 checks pass without those desktop runtime dependencies.

All 32 local manifest entries were audited. Updated the changed bridge hash and
one historical stale test hash (`bridge/operations.test.ts`, unchanged from HEAD).
The upstream SOURCE manifest and vendor source bytes are unchanged.

Evidence: `/tmp/pr190-pdf-crop-*.log`, type/manifest JSON receipts, final browser
source/download/receipt in `/tmp/pr190-pdf-crop-browser-evidence-final`, and archive
`/workspace/scratch/pr190-pdf-crop-evidence.zip`. Earlier failed iterations and
initial browser success are retained separately from final accepted evidence.

## Open boundaries

All-page crop/image drag UI, resize, extract/insert/replace, split/merge, Form
Design and other source commands remain open. No signed-PDF validity, desktop
viewer compatibility, real tenant/SQL/deployed network, distributed worker or
full application-image proof is claimed. Tasks 2–6 remain open; flags stay off.


Later paper-size status: the five-preset bounded source path is now accepted in
`NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md`. Historical Page Size open items above are
superseded only within that record's explicit source and composition limits.
