# PDF engine source and local boundary

Vendored from GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` (2026-11-05 snapshot), Apache-2.0. LICENSE and NOTICE accompany this subset. This is a selective Node-compatible subset, not the complete desktop PDF app. See the real feasibility probe in docs/research/genoffice-pdf-probe-2026-11-05.md.

## Source inventory and identity

SOURCE-SHA256.json maps each vendored TS path to its original upstream path and SHA-256. It covers 21 source modules: PDF main text/font/save/crypt/attachment/atomic-write/redaction dependencies, three shared IPC/radical/layer modules, six font-metrics modules, and electron-utils' pure Node atomic writer. The source bytes are unchanged except the explicitly recorded wasm-path.ts, save-pdf.ts and read-only text-edit.ts census adaptations. Local vendor package manifests expose only the copied modules and do not import the desktop package dependency tree.

LOCAL-SHA256.json records every current TS/MJS source and test, local package manifests, package-lock.json, LICENSE and NOTICE. For patched source, it records the current hash while SOURCE-SHA256.json preserves the upstream hash. Documentation, the hash manifests themselves, generated dist and node_modules are excluded. New local source files must be added to LOCAL-SHA256.json. bridge/* and the Python wrapper are smart_reporting additions; Python files live outside this source manifest's scope.

## Local patch

`src/main/wasm-path.ts`: accept an explicit AGENT_REPORTING_PDF_WASM_DIR containing `pdfium.wasm` and `hb-subset.wasm`, prefer this configuration, resolve standalone bundle-relative `../wasm` assets, and give a clear error for missing configured assets or a missing Electron resourcesPath fallback. Original node_modules resolution remains available.

`src/main/save-pdf.ts`: the image-edit and annotation-delete branches now throw explicit unsupported errors instead of dynamically importing absent desktop-only modules. This closes the frozen bridge capability boundary before bundling; no stub claims success, no Electron code is shipped, and the upstream SOURCE hash remains unchanged in the provenance manifest. The whitelist still rejects these operations before calling the writer. No PDF writer, layout engine or content-edit implementation was reimplemented.

## Allowed operations

The bridge reads a JSON request file at argv[2], returns one JSON receipt on the last stdout line, and writes errors to stderr with a nonzero status. inspect requests are `{kind:"inspect",input}`; patch requests are `{kind:"patch",input,output,sourceSha256,operations}`. It calls upstream applySaveRequest, takes the returned bytes and writes a new destination using exclusive creation (`wx`); existing output files, source aliases, hard links and symbolic links are not overwritten. It never calls savePdfToPath or its verification-before-write path.

At most 500 operations are accepted. Only highlight, addMarkup, removeMarkup, editNote, removeNote, replyNote, replyPendingNote, addTextAnnotation (sticky Text comment, not page-content text insertion), cropPage, setPageSize, addAttachment, removeAttachment, setFormValue, rotatePage, deletePage, reorderPages and identity-bound replaceText are accepted by a strict schema. Unknown fields/kinds, non-finite values, invalid colors/coordinates, stale source digest/page identity, duplicate reorder/delete, deleting all pages, and edits to a deleted page are rejected before invoking the writer. Coordinates are unrotated PDF user space within CropBox; UI conversion belongs to the caller. For addTextAnnotation the passed rectangle anchors the upper-left corner of upstream's fixed 20×18 pt sticky-note icon; it does not resize the icon. A rectangle wider/taller than the icon is accepted only as a positioning box.

Page IDs are `sha256:<source SHA-256>:page:<original zero-based index>`. The source digest is required at patch request level; optional per-operation sourceSha256 must agree if present. IDs are stable within one immutable source; after saving, inspect the new bytes to obtain new IDs. Operations reference original source page IDs. An optional single reorderPages must list every surviving page exactly once, even when deletePage appears later in the list. A page cannot be both deleted and otherwise edited in one request. Multiple rotatePage deltas on one retained page accumulate via upstream order. Empty operation lists return the exact original bytes.

The schema cannot pass image edits, generic annotation deletion, redaction, arbitrary upstream text-edit fields, inserted content text, encryption, arbitrary file paths or other upstream request fields. Upstream image-edit/annot-delete modules are intentionally absent; image-edit imports Electron. The local save-pdf adaptation explicitly rejects their requests, and they are unreachable through this bridge's whitelist. This is a documented subset, not a promise that arbitrary upstream save requests work.

## Development, bundle and deployment assets

Install with `npm ci --ignore-scripts --no-audit --no-fund`. `npm run test` exercises Node operation/asset boundaries; Python integration tests use an independent pypdf reader. `npm run bundle:bridges` emits dist/cli.mjs for the shared office_engine.run_bridge launcher.

The bridge is now a standalone production bundle: pdf-lib, PDFium JS, zod and all reachable local modules are included. `dist/metafile.json` is checked by the unchanged shared `docker/package-office-engine.mjs`, which rejects every non-builtin external import. There are no runtime node_modules, TypeScript source, Electron imports or unresolved dynamic imports. The bundle enables only the declared basic operations and the separately gated identity-bound text replacement contract described below.

Run `npm run bundle:bridges -- --metafile=dist/metafile.json`, then `npm run package:runtime -- /absolute/runtime/destination`. The PDF-specific package script invokes the shared strict packer, verifies both WASM files against fixed SHA-256 before creating the destination, and copies them to `wasm/` with `WASM-SHA256.json`. It separately retains HarfBuzz and PDFium license/README/manifests, including packages whose WASM is absent from JS metafile inputs. The optional third script argument selects the shared packer path in Docker; it does not relax verification.

Docker's separate `report-pdf-engine` build stage uses Node 22 and installs only this subset's pinned dependencies. Runtime files are copied to `/opt/reporting-pdf-engine`; `AGENT_REPORTING_PDF_ENGINE_DIR` and `AGENT_REPORTING_PDF_WASM_DIR` point to that standalone location. The app-source stage strips PDF development files alongside the two existing engines. Actual full application readiness/UI integration remains a separate task.

Fixed deployment asset inventory:

- PDFium @embedpdf/pdfium 2.15.1 runtime JS plus `dist/pdfium.wasm` (4,646,932 bytes, SHA-256 `5e4cd023c3dad4a895b3571ca573d3fc51bac6de48360d95283134385b954eaa`).
- harfbuzzjs 0.10.3 `hb-subset.wasm` (634,892 bytes, SHA-256 `3a5d246b0e4c0017084775e9f2c7fce96e45d09b1a354fd9e2e440c88fb9890d`); basic annotations do not call it; identity-bound text replacement uses the actual subsetter.
- pdf-lib 1.17.1 and transitive runtime JS bundled into `dist/cli.mjs`; dependency license and package metadata retained in `licenses/`.
- If deploying explicit assets, copy both WASM files into AGENT_REPORTING_PDF_WASM_DIR; plain Node has no process.resourcesPath.
- Fonts are not distributed here. Text replacement depends on actual installed fonts and can skip unsupported glyphs. The readiness probe exercises the same real CJK/numeric rebuild path instead of inferring support from font extensions; system TTC extraction is supported by the vendored font resolver.

No publication, validation or download-link policy is implemented in this engine; caller publication must preserve generated, identity-readable bytes and report validation failures without blocking links. Frontend/API integration and product text-edit controls remain outside this package's scope.

## Verification (2026-11-05)

`test_pdf_engine_runtime_package.py`: three initial tests failed before the runtime packer existed, then passed after bundling and packaging. The local Node and real Node 22 Docker runs execute inspect/patch in an isolated directory with no source or node_modules, with networking disabled in Node 22. Independent pypdf checks page order, rotation, highlight, Chinese sticky-note text, output digest and original bytes; both WASM hashes and dependency licenses are checked. Missing resources are rejected before creating the destination. A separately added changed-WASM regression also passed. These are four new targeted cases, not a repeat of the prior 13 Python operation tests.

Actual image evidence: `docker build --target report-pdf-engine -t smart-reporting-pdf-runtime:20261105 .` completed from pinned lockfile on Node 22.23.4. Its `/runtime/reporting-pdf-engine` output was extracted and inspected in a separate Node 22 container with networking disabled, without build source/node_modules. The full Python/LibreOffice application image was not rebuilt in this slice.

## Identity-bound text replacement (Task 9)

`src/main/text-edit.ts` has one appended local read-only `inspectTextObjects` export.
It calls the existing PDFium object walker, bounds/text/font readers and document
lifecycle functions; it does not replace the upstream matcher, font resolver,
HarfBuzz subsetter or content writer. Embedded font digests are cached per actual
PDFium font handle within a census to avoid copying a large font for every object.
The original SOURCE hash remains retained separately from the local hash.

`inspect` accepts optional `includeText` (default false). The basic path does not
load PDFium or resolve fonts. With text enabled, each page has `textObjects` with
`objectId`, `text`, `rect`, `fontName`, `fontSize`, `fontSha256` and
`expectedTextSha256`. The object ID binds the immutable source digest, original
page index, top-level/Form ordinal path, exact text and bounds. Empty/unreadable physical text objects are retained for overlap detection and
are not editable targets; callers should not offer empty strings for selection.
A client cannot
supply its own oldText, rectangle, font choice, size or arbitrary writer options.

`replaceText` accepts only `pageId`, `objectId`, `expectedTextSha256`, `newText`
and optional matching `sourceSha256`. Replacement length is capped at 4000 UTF-16
code units. Each target is relocated from the actual source bytes and must have
one unambiguous object at its ink bounds; repeated visible text elsewhere is
allowed because the object identity and geometry differ. A target can be edited
once per request. Multiline reflow is unavailable. The real upstream validation,
font selection, subset embedding and content rewrite execute on a candidate copy;
its output is then read back. The replacement must remain within CropBox, avoid
other original text ink, retain the original line box with at most 0.4em vertical
and one-em rightward growth for font substitution, and have extractable matching
text. Unsupported/missing glyphs, ambiguous/stale objects and overflow return a
specific `skippedOperations` entry and preserve their original source objects.
When every operation skips, the result is the exact original bytes. Mixed requests
keep valid changes and skipped originals. If upstream's combined rewrite reports
any text skip, all text replacements retain original content while independent
basic page/annotation operations still apply.

Patch receipts add `appliedOperationIndices`, `skippedOperations` and
`previewDigest`. Python `patch_pdf_with_receipt` returns these plus actual
`content: bytes`; callers must surface skip reasons. The legacy bytes-only
`patch_pdf` raises `pdf_text_operations_skipped` if any text operation skipped,
so unknown consumers cannot silently claim all requested changes succeeded.
API publication uses the receipt path and its own explicit confirmation policy.

The stable preview digest binds the source, parsed operations, actual applied/skip
decisions, final PDFium-readable text/bounds/font metadata, embedded font-program
SHA-256 and both actual runtime WASM file digests. Output object IDs containing
non-deterministic PDF file IDs are excluded; actual font programs and output
geometry are retained. The actual output file SHA/size remain separate verified
receipt fields. An extra valid WASM custom section changes the confirmation digest
while preserving editing behavior, verified by a real subprocess test. The API
must recompute at save, compare the confirmation, and write that same returned
content without generating it again.

A `textResources` CLI request and Python `check_text_resources()` readiness probe
actually rebuild `报告金额一二三123` from Helvetica using the deployed resolver,
PDFium and HarfBuzz, then read back the output and require embedded font SHA values.
It returns `{ok, fonts, resources, issues}` and has a 15-second subprocess timeout;
there is no invented font-path environment variable and no extension-only check.

New targeted Python tests exercise real Latin numeric, Latin-to-Chinese and
Chinese-to-Chinese replacements with independent pypdf extraction and Poppler
PNG comparison, control text/background retention and absence of annotations.
They also cover repeated text identity, stale text/object identity, missing glyphs,
overlong/multiline/overflow constraints, exact-original skip behavior, mixed
success/skip behavior, preview stability, actual WASM identity changes and real
resource readiness. No claim is made for OCR, paragraph reflow, arbitrary rotated
or complex-script content, redaction/forensic erasure, or all real-world PDFs.


## Native current-page crop adapter (2026-11-06)

`bridge/operations.ts` accepts strict `cropPage` with immutable `pageId` and a
finite four-number `rect` in unrotated PDF source coordinates. Each crop must
shrink the current CropBox (minimum width/height 0.5 user units); source checks,
500-record budget and edit/delete conflicts remain enforced. Final source IDs
map through output deletion/reorder, using the same pdf-lib `setCropBox` primitive
as pinned `cropPagesBytes`, with automatic field appearances disabled. MediaBox
and underlying content remain. This is a source-space native adapter, not a new
PDF serializer or redaction. Browser display margins are converted with PDF.js.
See `report_editor/NATIVE_PDF_CROP_ACCEPTANCE.md` for independent pypdf, browser,
ASGI and Node22 boundaries. Vendor and SOURCE hashes are unchanged. Local SHA
audit refreshes the bridge and one historical stale existing-test record.


## Five-preset paper size (2026-11-06)

Strict setPageSize accepts preset A3/A4/A5/Letter/Legal and calls the unchanged
upstream setPageSizeBytes after other source-coordinate edits and final order/
deletions. Only one is accepted; cropPage/replaceText mixtures reject. Inspection
provides pageSize/pageSizeReason: UserUnit other than1, signatures/unsupported
fields/XFA, outline/destination/name catalogs, auxiliary print boxes, non-quarter
rotations and unmodeled annotation kinds are conservatively readonly for size.
The source writer's already-matching-page skip and changed-page crop reset are
retained. Output identity is included in the size preview digest; the native
service returns a receipt even when the independent text feature is disabled.
No vendor or upstream hash change. See
`report_editor/NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md` for raw UserUnit limitation,
actual files/browser/service/Node22 evidence and exact restrictions.


## Selected-text markups (2026-11-06)

Strict addMarkup binds source/page identity, one of highlight/underline/squiggly/
strikeout,1–200 canonical axis-aligned PDF-space quads and finite RGB. Current
CropBox/deleted-target rules apply before the unchanged markups/AP writer runs.
Inspection exposes readable source marks and markupReadSafe; malformed relevant
QuadPoints make that page readonly for this new operation. Selection controls
require selectionMarkup capability; old rectangle-highlight requests remain.
The native service provides actual-output preview receipts without the text
feature flag, binding the preview digest to markup output SHA as well as intent.

The renderer annotations helper is separately adapted with source/current SHA,
local type import/content-box selector and prominent notice under frontend/src.
No Node vendor or upstream SOURCE hash changed. See
`report_editor/NATIVE_PDF_SELECTION_MARKUP_ACCEPTANCE.md`; safe saved-markup removal is now implemented by a strict source adapter; see
`report_editor/NATIVE_PDF_MARKUP_REMOVAL_ACCEPTANCE.md`. Generic vendor deletion
requests remain unsupported.


## Existing sticky-note continuation (2026-11-06)

Strict editNote/removeNote records use immutable source/page/annotation identities
and dictionary hashes. The native adapter applies the source Contents/M primitives
without geometry fallback or fail-soft skips, preserving the edited object and
copying Annots arrays for deletion. A staged UTC modifiedAt makes repeated preview
and save deterministic. The vendor writer is unchanged. Replies/popups/rich text/
locked/shared/direct/protected or unreadable sources remain readonly.

Raw AcroForm/XFA must be captured before pdf-lib getForm(), which deletes XFA in
its memory model. That source flag now protects note/markup mutations, size and
form-field editability. This does not certify arbitrary XFA operations. Tests,
artifact identities, original-source references and runtime evidence are in
`report_editor/NATIVE_PDF_SAVED_NOTES_ACCEPTANCE.md`; whole PDF parity remains open.


## Pending-note actual preview and creation time (2026-11-06)

addTextAnnotation accepts optional integer createdMs0–253402300799999. The native
bridge forwards the staged instant to the unchanged note/AP writer, then verifies
base+markup+note counts and exact appended Text payload/round2 Rect before
canonicalizing only new CreationDate/M to UTC. Legacy untimed additions omit
unknown optional dates; existing source metadata is retained. This replaces the
old save-time default for legacy new annotations without inventing a creation date.
The actual output SHA now binds their preview receipt. No global TZ/clock override
is used in product code. Source-writer cross-zone counterexample, guards, actual
preview/save/download and legacy compatibility proof are documented in
`report_editor/NATIVE_PDF_NOTE_PREVIEW_ACCEPTANCE.md`. Vendor SOURCE hashes unchanged.


Inspect note references (2026-11-09): optional note `sourceRef` is the original
indirect object's full number/generation key matching PDF.js IDs (`80R3`, zero
`80R`, direct dictionary null). It supports a readonly sidebar join only; strict
write schemas still reject it and require annotationId/dictionary digest. The
new focused bridge test covers nonzero generations and direct-note readonly.
No upstream vendor source or write protocol changed. LOCAL-SHA256 has36 entries.


## Native bounded attachment write adapter (2026-11-09)

`bridge/attachments.ts` wraps unchanged pinned `src/main/pdf-attachments.ts`.
The source writer uses EmbeddedFiles name-tree keys, removes before adding,
preserves existing Filespec references and refuses Kids trees. The native adapter
adds immutable source/key/Filespec+stream/content identities, canonical payload
and decoded-byte budgets, bounded Flate inspection, conservative reference and
protection census, intermediate/output content verification and encoded-string
byte ordering (the source writer sorts decoded labels). Only flat, unambiguous,
unshared embedded files are writable. Associated/linked files, signature/XFA/
permission sources, unsupported filters and complex structures remain readonly.
Removed objects can remain in the PDF; no secure erasure is claimed.

Added data is limited to2 MiB/file and6 MiB/batch; source census is bounded to
200 entries,20,000 indirect objects,8 MiB decoded/file and24 MiB decoded total.
Native operation count/JSON and online source size limits remain in force.
Attachment writes run after page/form/note work and verify source survivors.
Text-replacement combinations are refused until their preservation contract is
verified. No vendor source, WASM, dependency or signing route changed.
See `report_editor/NATIVE_PDF_ATTACHMENT_WRITE_ACCEPTANCE.md`.


## Native exact-parent reply adapter (2026-11-09)

`bridge/note-replies.ts` reuses the unchanged pinned note-reply drawing branch in
`save-pdf.ts`, but never accepts its fallback to a root note. Public replyNote
requests bind source/page/annotation identity and dictionary digest, with required
creation instant and bounded contents. A conservative object/reference census
allows only safe saved flat roots and standard same-page RT/R children. Protected,
shared, nested, popup, rich, locked/hidden or ambiguous sources remain readonly.
The writer runs after other supported page/form/note/attachment stages. Exact
parent reference/dictionary must still match before writing; appended counts,
payload, IRT/RT, UTC dates and every pre-existing annotation are verified after.
Root edit/delete and text/crop/page-size mixtures are refused. Five new engine
cases include actual original-writer orphan and wrong-identical-parent
counterexamples. See `report_editor/NATIVE_PDF_REPLIES_ACCEPTANCE.md`.


## Native pending-root reply adapter (2026-11-09)

`bridge/local-note-replies.ts` uses the pinned note drawing's localId and
replyToLocalId fields unchanged. Strict addTextAnnotation accepts an optional
32-hex localId; replyPendingNote requires same-source page ID, parentLocalId,
contents and creation instant. Duplicates, absent/cross-page parents, protected
sources and unsupported geometry/text mixtures fail before creating output.
Referenced roots are deferred out of the ordinary drawing stage, then all roots
are written before their replies after supported page/form/note/attachment work.
Appended-note verification maps actual new references to roots, rejects aliases
to old or other new notes, checks root/IRT/RT and payload/date contracts, and
preserves every existing annotation dictionary/reference. Draft local IDs are not
written into PDF metadata. The source/visit census is shared with saved-root reply
validation. Existing ordinary-note/text combinations retain their prior checks.
See `report_editor/NATIVE_PDF_LOCAL_REPLIES_ACCEPTANCE.md`.


## Native saved flat-leaf reply mutation (2026-11-09)

The shared source census now exposes safe reply leaves with parentAnnotationId.
Strict editNote/removeNote and the existing markup-delete adapter are reused,
with no new public operation schema. Safe leaf edits preserve identity, IRT/RT,
creation time, author, geometry and AP; only Contents/M change. Deletion unlinks
the exact page slot and releases the globally unshared leaf dictionary. Leaving
that dictionary behind retains an inbound IRT and makes the conservative future
census readonly, as shown by a real counterexample. All surviving annotation
references/dictionaries are read back after mutation. Source thread protection,
flags/links and global counts remain authoritative; root/thread subtree and complex
mutations remain unsupported. Leaf mutations cannot mix with text/crop/size work.
The original annot-delete.ts blob660951ad1e2556276245f64054af23fd4929e081
was fetched at the fixed ref as a semantic/fallback reference; its PDFium matching
path is not shipped or executed for these operations. No vendor/dependency/WASM
change. See `report_editor/NATIVE_PDF_SAVED_REPLY_EDITS_ACCEPTANCE.md`.


## Native secure redaction adapter (2026-11-10)

The bridge `redact` operation (`{pageId, rect}` in PDF user space, inside the
crop-aware visible box, ≤ MAX_REDACTION_REGIONS) calls the unchanged pinned
`src/main/redaction.ts` `redactPdf` as the final serializer of the native patch,
after every pdf-lib pass (crop, attachments, note replies), with page indices
mapped to the final page order and page `/Thumb` + `/PieceInfo` removed first —
the same steps `applySaveRequest` performs before its own redaction pass. Every
native save writes a new revision and leaves the source revision unchanged, which
is the pinned "redact a Save As copy" requirement. Redaction is rejected on blank
draft pages and together with a page-size change. `bridge/redaction.test.ts`
reads the output text back with PDFium. Vendor SOURCE hashes unchanged;
LOCAL-SHA256 has 47 entries.


## Native merge pages / split pages adapter (2026-11-10)

Bridge `mergePages` (`perSheet` 2–16, `direction`, `separator`) and `splitPages`
(`perPage` 2/4/9) call the unchanged pinned `mergePagesBytes` / `splitPagesBytes`.
Like the pinned commands, they write a new file — here a new revision; the source
revision is unchanged. Each must be the only operation in its save, is refused for
sources with signature fields, and is checked by reading back the expected page count.
The pinned writers stamp the new document with the current time; the adapter copies
the source CreationDate/ModDate (or drops them) so an output — and its preview digest —
is reproducible from the source bytes and operation alone.
`bridge/page-layout.test.ts`. LOCAL-SHA256 has 48 entries.

Native preservation follow-up: `bridge/layout-preservation.ts` uses the fixed PDFium 2.15.1 FPDFPage_Flatten normal-display API, serialized through the existing chainPdfium/withDocument/saveDoc helpers, before N-up embedding. It reuses the local note adapter reference census to refuse recoverable annotation graphs before redaction. The vendored redaction/save implementation and WASM are unchanged. Split with form fields and both layouts with XFA are refused rather than emitted with missing fields/content.
