# PDF Office / text conversion — 2026-11-11

## Implemented

- PDF → DOCX/XLSX/PPTX uses upstream ref f8c17004fb730df11f0f743164ffd8b4281bb38c extraction/analysis/rebuild. The 48-file source/local hash closure is verified.
- DOCX uses the existing docx-engine. XLSX uses the upstream cell builder and a declared local adaptation: scan/degraded page rasters are embedded by existing xlsx-engine applyStaticImage. Normal-page source images now use labelled image reference areas after editable cells; exact original image/text placement and vector decor remain unsupported. See NATIVE_PDF_XLSX_IMAGES_ACCEPTANCE.md.
- Derived Office files preserve source-parent identity and independent document/revision/SHA/size. Postwrite/review/registration faults retain actual readable downloads.
- Markdown/HTML first creates real DOCX, verifies parent SHA and same-origin signed download actual SHA/size/ZIP signature, then uses existing Docs parse/Editor plus upstream documentToMarkdown/buildStandaloneHtml. Images are self-contained data URLs; HTML is attachment-only. Session Blob downloads retain generated Word fallback after late browser failure.
- OCR is never supplied. Scan pages remain images. Every conversion keeps validation.ok=false pending manual review.

## Verified evidence

- New DOCX/XLSX requests initially failed the prior PPTX-only schema. The expanded engine tests generated actual files in /tmp/pdf-office-multi-20261111. Independent python-docx reads four expected paragraphs; openpyxl reads expected Page 1/Page 2 content; scan packages both contain PNG media.
- Frontend identity/concurrency/late-failure: 9 passed. Real unmocked DOCX→Editor→source serializer text/table/PNG tests: 2 passed; output has data:image/png;base64 and no folder token/lazy-media URL. jsdom does not validate real layout.
- Dedicated complex PPTX test passed: embedded DejaVu Sans/Unicode, two columns, 3×3 table, raster chart and link. python-pptx independently reads 1 table, 1 picture, 7 text shapes and expected text. Font names include DejaVu Sans and Chrom Sans/Serif/Fixed substitutions. Evidence: /tmp/pdf-complex-fidelity-20261111. Child-sandbox LibreOffice did not produce a PDF. Root later successfully rendered converted.pdf; its visual review found abnormal table character wrapping, recorded below. Full visual fidelity is not claimed.
- True browser runner: frontend/smoke/pdf-convert-formats-smoke.mjs with dedicated wrapper server appending a fourth scan-only page. Uses production assets, real native grant/cookie/CSRF, packed engine, publication and signed Office downloads. Independently reads Office content and decodes MD/HTML embedded PNGs. Actual outcome must come from its summary.json.

## Remaining fidelity limits

Exact fonts/embedding, pagination, floating objects, headers/footers, form/annotation semantics and arbitrary reading order remain unaccepted for full fidelity. Reflow is possible. Some Markdown readers omit data-URL images; Word/HTML remain fallback downloads. OCR/scanned-page editable text are intentionally absent.


## Actual root01 browser acceptance

The frozen-production-assets browser run passed at
/tmp/pdf-convert-formats-browser-20261111-root01/summary.json. Chromium version:
140.0.7339.16. Production manifest SHA-256:
eeb712aacbd867023a226b2e06c794188a0026a014b9403aea1698a1e85b947d.
Source SHA-256:
4c8b71bec2ebb86b3e71e5e04d4e8936d29a6160c5634cd0c7fc5daac02ad3c8.
The real native grant/cookie/CSRF/packed-engine/publication/signed-download
flow passed for DOCX and XLSX; independent python-docx/openpyxl reads succeeded.
Markdown (4109 bytes) and HTML (6054 bytes) actual browser Blob downloads were
self-contained; scan PNG resources were independently decoded. Source remained
unchanged; page/console/HTTP error lists were empty. All conversions retained
manual-review status. This run predates the subsequent PPTX cell-flow fix.

## Complex PPTX visual follow-up

Root successfully rendered the original complex output to
/tmp/pdf-complex-fidelity-20261111/converted.pdf. Visual comparison identified
unwanted wrapping in Region, 12345.67 and percentage cells despite correct
column widths. The source adapter had copied all trailing cell whitespace into
a huge right inset, reducing flow width to tight PDF glyph-ink bounds.
A minimal local table adapter fix preserves source alignment anchors, releases
unused trailing whitespace, and uses zero horizontal inset for inferred centered
content. Column widths, fonts and default wrapping writer are unchanged.
The complex fixture width regression and left/center/right model cases each
showed RED→GREEN. Dedicated isolated bundle produced converted-fixed.pptx, SHA:
0a391830a05f894e239518582b013f883dabfe79a896423eeac6cc3f9af53dd7.
Root later independently rendered the subsequent font-and-table corrected artifact
and visually confirmed the two specific fixes, recorded below. No full-fidelity
pass is recorded here.


## PDFium output-font alias follow-up

The complex output exposed another definite gap: PDFium reports built-in
Helvetica/Times/Courier substitutes as Chrom Sans OTF, Chrom Serif OTF and
Chrom Fixed OTF. The existing output map did not recognize these names, leaving
Office to guess from an unavailable family name. Three known aliases now reuse
the existing metric-compatible Helvetica/Times/Courier candidate lists. Installed
source families still win and unavailable/unknown families remain unchanged.
The deterministic injected-installed-check test showed three failures before the
change, then seven passes. Evidence:
/tmp/pdf-output-font-aliases-red-detail.log and
/tmp/pdf-output-font-aliases-green.log. All 48 local vendored hashes match the
source manifest; original source hashes remain separate.

The isolated real conversion produced
/tmp/pdf-complex-fidelity-20261111/converted-font-fixed.pptx (7788 bytes), SHA-256:
7680460f87c7eae8a00b0e2df4dc4d67bdc1fa1563654540f19d3b20870829e0.
Independent ZIP XML reading finds DejaVu Sans, Liberation Sans, Liberation Serif
and Liberation Mono instead of the Chrom names. Parent source identity is
6447bd9cbdbd5451979dd31773846c61e55c87d202012a59e7cb56b88ef987ba.
This artifact includes the prior table-flow correction. Root independently
rendered it with LibreOffice to
/tmp/pdf-complex-fidelity-20261111/converted-font-fixed.pdf and compared
converted-font-fixed-render.png with source-render.png. The visual review
confirmed that table labels, values and percentages no longer wrap into stray
characters, and that the Code001 fixed-width caption is visibly monospaced.
The two-column layout, chart, table and Unicode content remain present.
Text positioning, line spacing and substituted-font appearance still differ;
this is confirmation of these two defects being corrected, not full-fidelity
acceptance. The conversion continues to return validation.ok=false and the
font/layout warnings.

Root's final runtime at /tmp/pdf-text-convert-form-runtime-20261111 includes both
the font alias and table-flow corrections. The extended form browser run at
/tmp/pdf-form-extended-browser-20261111-root03/summary.json separately passed all
six revisions with serial execution and TMPDIR=/dev/shm. This form regression
does not replace conversion layout review or change conversion validation status.
