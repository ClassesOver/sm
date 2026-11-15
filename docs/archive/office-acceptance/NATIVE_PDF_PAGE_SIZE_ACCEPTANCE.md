# Native PDF paper-size acceptance

2026-11-06. Connects `genoffice.pdf.page.size` for bounded sources and the fixed
five paper presets. Task 5 and arbitrary-source/desktop parity remain incomplete.

## Original sources and semantics

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- `apps/pdf/src/renderer/view-config.ts`, Git blob
  `798e06a8a85291c5ce9631c968bd460ae9b3bd6f`, lines 41–47: A3 842×1191,
  A4 595×842, A5 420×595, Letter 612×792, Legal 612×1008 (PDF points).
- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, lines
  6517–6518 and 11833–11860: apply the selected preset to the whole document.
- Vendored `src/main/save-pdf.ts:1276`, unchanged `setPageSizeBytes`: uniformly
  scale content and annotations from MediaBox, center by shifting its origin,
  swap raw target dimensions for 90/270-degree pages, and set CropBox to match.
  Pages whose raw dimensions already match are skipped, including their crop.

The native strict record is `{kind:"setPageSize",preset:"A4"}` (five allowed
labels only), bound to the required source digest. At most one paper record is
accepted; its transform runs after ordinary source-coordinate operations and
final page removal/reorder, applying to every surviving output page. Existing
form-value/annotation/rotation/order operations can compose with it. Crop and
replaceText mixtures are rejected; save/reopen is required between them.

The UI keeps source geometry for editing, stages one history step, then renders
actual engine-written PDF bytes. Actual preview viewports use output page bounds,
not stale source CropBoxes; fit/zoom resolve reordered preview indices. Returning
to the source permits Undo/Redo or other supported source edits. Saved drafts
restore the preset; preview can be regenerated. Size-only changes do not acquire
the text feature flag or a new manual confirmation requirement. Existing text
review/digest enforcement remains intact.

The dialog states that changed-size pages reset their CropBox, and already-sized
pages remain as they are. Selection is explicit; saved files are new revisions.

## Conservative source boundary and raw counterexample

`inspectPdf.capabilities.pageSize` must explicitly be true. The bridge refuses
non-default UserUnit, signature/unsupported fields, XFA, catalog outlines/destinations/
names, auxiliary print boxes, non-quarter-turn rotation and annotation subtypes
outside Text/Widget/Highlight/Underline/StrikeOut/Squiggly. Unparsed gate metadata
fails closed for this capability without disabling existing PDF operations.
These are source-level restrictions, not a claim that all coordinate semantics
in arbitrary PDFs were ported. The gate considers the original document even
when an unsupported page is pending deletion; save/reopen can change the source.

A raw call to unchanged upstream setPageSizeBytes requested A4 595×842 on a
UserUnit=2 source. Independent pypdf readback found physical dimensions
**1190×1684**, confirming the limitation rather than assuming a model fix.
Source/output/receipt are retained in
`/tmp/pr190-pdf-size-upstream-limitation`. The native source gate refuses this file.
The vendor and upstream SOURCE-SHA256 manifest are unchanged.

## Actual file and service verification

`reporting/tests/test_pdf_page_size.py`: **35 distinct new cases passed across
focused runs**. Twenty combinations of five presets and four rotations check
media/crop origins and dimensions, actual scale matrices, extractable text,
widget/note rectangles and form values using independent pypdf. Further cases
cover ordered rotation/delete/reorder/form writes, deterministic preview digests,
six unsafe source variants, bad/extra/duplicate/stale records, forbidden crop/text
mixtures, and the upstream already-matching-page crop/content no-op.
Initial 34 passed; the added matching-page case and affected composition case
passed with the final packed runtime. Repeated checks are not added to the count.

All **40 affected existing** bridge/crop file cases passed. Frontend **7 new**
preset/protocol/history checks plus **46 affected** inventory/crop/batch/operation
checks passed (53 total). Both production builds include strict frontend typing.

One new native service scenario passes with pdf_text_enabled=false: real output
preview/digest and preview file, changed-preset digest refusal, actual revision2
save and signed-download streaming, original text retained and validation failure
still returning the download. All **3 existing text service** checks also pass.
These use synthetic scope/in-memory repositories; they are not deployed HTTP/SQL
or production tenant authorization proof. Publication/signing code is unchanged.

Final packed bridge on Node22 in a readonly/network-none container: **2 passed,
33 deselected**, covering composition and matching-page semantics. This is mounted
runtime evidence, not a complete application image. Runtime CLI SHA256:
`3397d9fd01ba00532d23c4e555f469400ab1266f124a9e7f40f82b36a42532cf`.

## Browser/file evidence

`frontend/smoke/pdf-page-size-smoke.mjs`, Chromium154.0.8037.57, production static
assets, actual packed bridge; authentication/revision routes are substitutes.
The fixture includes nonzero MediaBox origin, an existing crop, three rotations,
three form fields and a note. It changes fields, rotates source page0, deletes
source page1 and reverses source survivors to 2/0, then selects A4.

Actual output preview displays **595×842** on both retained pages, despite raw
rotations 180/90. It checks cancel, source return, crop-disabled state while size
is pending, one-step Undo/Redo, genuine refresh recovery, regenerating actual
preview, save/download and revision2 reopen. Readonly forced dispatch cannot open
the size dialog; console/page errors are empty. pypdf independently reads:

| Source index | Rotation | MediaBox and CropBox |
| --- | --- | --- |
| 2 | 180 | [14.875,-19.375,609.875,822.625] |
| 0 | 90 | [-171.1,23.8,670.9,618.8] |

All source text remains; widgets and note rectangles scale by the expected
per-page factor, and contact=Ada/consent=/Off/plan=/pro survive.
Source SHA256: `5ff27dd49e8fb1d6fb02e2f14bef8409fd384a637ddceed182b22ecf915cabc7`.
Download SHA256: `85fc47ccac0c5a32993236c34410dbbbfa511ad1f4a9de9b2c239557e8bbeea1`.
Originals/receipt: `/tmp/pr190-pdf-size-browser-evidence-final`.

The first browser route substitute omitted X-Native-Preview-Digest and correctly
failed the client's existing header check. The fixture was fixed to match the
real API; no product bypass was added. An initial bridge type check found a tuple
spread error; explicit width/height arguments fixed it. Final baseline comparison
has zero new diagnostics but retains six existing missing desktop type-only
packages/Electron properties. This is not reported as a clean standalone bridge
tsc pass. Earlier failure logs remain in the archive.

## Build, provenance and open work

Final standard/Slides builds pass (33.18s/36.34s), actual bundle budget and budget
contract pass. Ruff, smoke syntax and diff checks pass. Existing third-party chunk
warnings remain. All 32 local SHA entries were checked; only the changed bridge
hash needed refreshing. No full repository/frontend suite was repeated.

Archive `/workspace/scratch/pr190-pdf-page-size-evidence.zip` contains logs, final
browser bytes/receipt, raw upstream limitation, original source excerpts and
manifest/type receipts. Source docs and preset model are committed for replay.

Custom sizes, source structures rejected above, crop/text combinations, desktop
visual compatibility, signed-file validity, full application image, production
identity/SQL/network and full source command parity remain open. PDF extract/
insert/replace, split/merge and Form Design are still unavailable. Flags remain
off; Tasks 2–6 remain incomplete and the PR stays draft.
