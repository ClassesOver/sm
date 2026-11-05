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

At most 500 operations are accepted. Only highlight, addTextAnnotation (sticky Text comment, not page-content text insertion), rotatePage, deletePage, reorderPages and identity-bound replaceText are accepted by a strict schema. Unknown fields/kinds, non-finite values, invalid colors/coordinates, stale source digest/page identity, duplicate reorder/delete, deleting all pages, and edits to a deleted page are rejected before invoking the writer. Coordinates are unrotated PDF user space within CropBox; UI conversion belongs to the caller. For addTextAnnotation the passed rectangle anchors the upper-left corner of upstream's fixed 20×18 pt sticky-note icon; it does not resize the icon. A rectangle wider/taller than the icon is accepted only as a positioning box.

Page IDs are `sha256:<source SHA-256>:page:<original zero-based index>`. The source digest is required at patch request level; optional per-operation sourceSha256 must agree if present. IDs are stable within one immutable source; after saving, inspect the new bytes to obtain new IDs. Operations reference original source page IDs. An optional single reorderPages must list every surviving page exactly once, even when deletePage appears later in the list. A page cannot be both deleted and otherwise edited in one request. Multiple rotatePage deltas on one retained page accumulate via upstream order. Empty operation lists return the exact original bytes.

The schema cannot pass image edits, annotation deletion, redaction, arbitrary upstream text-edit fields, inserted content text, encryption, arbitrary file paths or other upstream request fields. Upstream image-edit/annot-delete modules are intentionally absent; image-edit imports Electron. The local save-pdf adaptation explicitly rejects their requests, and they are unreachable through this bridge's whitelist. This is a documented subset, not a promise that arbitrary upstream save requests work.

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
