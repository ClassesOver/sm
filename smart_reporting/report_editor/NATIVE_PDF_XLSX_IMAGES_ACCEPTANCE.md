# PDF → XLSX normal-page images — 2026-11-11

## Implemented scope

The bridge reuses the fixed-source PDF ImageBlock payloads, the existing
rebuildXlsx sheet models and planPageGroups, and xlsx-engine applyStaticImage.
It does not invent a text/table layout engine. Since upstream cells are
reflowed, source pictures are placed in labelled image reference areas AFTER
all editable cells (including the full merged-row extent). Continued-table
pages bind to their actual grouped worksheet, with a separate reference area
per source page. No full-page scan is overlaid on normal editable cells.
The source page display-space picture arrangement is retained inside each
reference area at 1pt = 12700 EMU. Row heights are explicitly 15pt. Column
markers follow the existing workbook renderer's 96-DPI/seven-pixel digit
convention and serialized two-decimal column widths.

IR image payloads already include object transforms, transparency and PDF page
rotation. The fixed-source cell-data quarter-turn recovery rotates geometry
without turning encoded pictures; the precise already-chosen recovery turn is
now metadata propagated to IrPage. The bridge reuses the existing inverse
rotateToDisplay helper to restore source display-space boxes. No pixel rotation
is guessed or repeated. The three metadata-only vendor changes retain separate
original/local SHA records, with all 48 local hashes verified.

PNG images crossing visible page bounds are decoded with the PNG decoder
already bundled inside pdf-lib, cropped through the upstream cropRgba helper
and encoded through its PNG writer. Their pixels are cropped, not squeezed
into the clipped anchor. Alpha survives. Outside-page pictures are skipped
explicitly. Boundary-crossing JPEG cropping is not supported and produces a
specific partial-retention warning. Other known limitations remain: excluded
synthetic vector decor, pictures already suppressed by upstream analysis,
font/reflow differences, print pagination and exact original picture/text
relative placement. This is partial picture retention, not original-layout
fidelity. All conversions retain validation.ok=false and manual-review warnings.

## Budgets and failures

The bridge embeds at most 100 source pictures per document, 20 million pixels
per image, 100 million pixels total and 32 MiB encoded image payload total.
Existing 24 MiB PDF / 50-page / source-render budgets are unchanged. Images
outside budget or with invalid geometry are skipped with page/image warnings.
The last successfully generated workbook bytes survive each failed image
write; later pictures continue. Reference-area preparation failures similarly
preserve the existing workbook and give a specific warning. Scanned/degraded
pages retain the previous explicit single-image fallback and OCR stays absent.

Local interface:
embedXlsxPageImages(bytes, irPages, converted.sheets, writer?) → {bytes, warnings}.
The optional writer is only an internal test seam for failed image mutation.
No public API, download contract, shared workbook engine or dependency changes.

## Actual evidence

Fixture: bridge/fixtures/xlsx-normal-images.pdf, project-generated authored
three-page PDF, 4349 bytes, source SHA-256 1a37ae18aa6c9f68f1af9fbfaf6403c93dde961d2074c17b293f050ecdad0133.
It has editable text/table revenue plus three true RGBA pictures per page,
object rotation, nonzero-origin CropBox, page /Rotate 90 and boundary clipping.

- Missing-image regression: 0 != 9 before the implementation, then PASS.
- Separate page-rotation placement regression: RED before exact recovery metadata,
  then PASS.
- Helper tests: 5 PASS — actual continued-table sheet mapping, per-image write
  failure retaining numeric cells/later pictures, invalid/budget/JPEG/outside
  warnings, full merged-row extent, document-wide 100-picture budget.
- Directly affected prior Office conversion tests: 7 PASS (DOCX/XLSX/PPTX,
  scan image fallback, stale/protected input, output-review retention, budgets).
  This was a single targeted regression run, not a repeated full suite.
- Independent openpyxl/OOXML/Pillow checks: 3 worksheets, editable 12345.67
  numeric cells, 9 actual media pictures, all 9 source-display-space anchors
  within 0.001pt, alpha 128–255, exact interior RGBA samples for object/page
  rotation and cropped images. Output 10942 bytes, SHA-256
  7e505226b5a45225a42988ecb5dce96cca34d5105ca12006db878d6d173f4f54.

Evidence directory: /tmp/pdf-xlsx-images-20261111. Includes red.log,
rotation-red.log, rotation-green.log, helper-final.log, office-regression.log,
converted.xlsx and independent-verification.json. Node 24 was used locally;
this does not establish a fresh Docker Node 22 build.

## Real browser acceptance

New frontend/smoke/pdf-xlsx-images-smoke.mjs uses the existing actual
native-grant/cookie/CSRF/packed-engine/publication/signed-download route through
its dedicated fixture wrapper server. It reads PDF_SMOKE_STATIC_DIRECTORY for
both manifest and every fetched JS file identity, matching the shared server
static-directory convention. The signed actual XLSX is independently read by
pdf-xlsx-images-verify.py. Source SHA stays unchanged and validation remains
manual-review. Syntax checks passed for the runner/server/verifier.

Root independently completed the final browser run. Evidence was read back from
/tmp/pdf-xlsx-images-browser-20261111-root02/summary.json and independent.json;
both record ok=true. Chromium 140.0.7339.16 used the frozen production snapshot
/dev/shm/pdf-next-static-20261111-root02 with manifest SHA-256
4f618f6766d44112982ccf8fd18384db72fec7bd8ba2e245d14c5f169fa68e09.
All 36 fetched JavaScript asset identities matched that snapshot. Root records
the runtime at /dev/shm/pdf-next-runtime-20261111 with CLI SHA-256
d57204f18ee14eb55d9ac3d1b98a4e3cfa4b1e2dc941417072d64bdfaac2c270.

The actual native grant/cookie/CSRF/packed-engine/publication/signed-download
flow returned a readable XLSX of 10942 bytes, SHA-256
55db1c6d587bd569d4da7557d1a564e422747bef5f340d50d0cfef3bebec900d.
Independent openpyxl/Pillow/OOXML checks confirmed editable numeric cells and
all nine source-page images, including their anchor/rotation/crop/alpha checks.
Source SHA remained
1a37ae18aa6c9f68f1af9fbfaf6403c93dde961d2074c17b293f050ecdad0133.
Asset, page, console and HTTP error lists are empty. The conversion retained
manualReview=true and overall validation=false; this verifies partial image
retention through the real download chain, not original-layout fidelity.

The first browser attempt at
/tmp/pdf-xlsx-images-browser-20261111-root01/failure.json failed in the smoke
harness after conversion had succeeded: it called issue.includes on a structured
validation issue. Root corrected the harness to String(issue.message ?? issue)
and added REPORT_EDITOR_CHROMIUM_EXECUTABLE support before root02. The first
attempt is not recorded as a pass. Root also registered the new test files in
the package test list and verified 151 local manifest entries and the 48-file
vendor closure. No production code changed during this acceptance-note update.
