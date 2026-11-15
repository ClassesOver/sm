# PDF → PPTX measured baseline spacing — 2026-11-11

## Accepted implementation boundary

Only the definite multi-line leading defect is corrected. The fixed-source
textBlockParagraph previously used glyph-ink block height / line count, although
IR Line.baseline already carries the authored baseline positions. In the
complex-layout.pdf fixture both columns have eight lines at 16pt baseline steps;
the old formula wrote 14.97pt on the left and 15.21pt on the right because the
outer glyph extents differ. The adapter now reuses the existing median helper
on positive finite adjacent baseline gaps, with the original fallback for a
single line or unavailable baseline metrics. Existing page scaling applies.
No text layout engine, guessed offset correction or font-metric reimplementation
is introduced. Paragraph/line text, hard breaks, textbox offsets and source font
substitution policy remain unchanged. Variable leading within one paragraph is
not reproduced by a single paragraph lineExact setting and remains unaccepted.

Fixed GenOffice source ref: f8c17004fb730df11f0f743164ffd8b4281bb38c.
Only vendor/pdf2docx/src/rebuild-pptx/text.ts has a production behavior change in
this batch. Original source SHA and adapted local SHA remain separately recorded
in SOURCE-SHA256.json. Existing font aliases, table padding and XLSX image
metadata adaptations are preserved. OCR remains absent. No shared slide writer,
CLI/API, dependencies, runtime packaging or static output was changed here.
The bridge's existing generated-byte preservation and manual-review status are
unchanged; no new post-generation rejecting step was introduced.

## Actual tests and direct conversion

bridge/pptx-text-geometry.test.ts: actual RED (3 failed / 1 passed) → GREEN
(4 passed), covering font-dependent ink boxes, scaled baseline spacing,
single-line/unavailable-metric fallback, and a real complex PDF conversion whose
both editable column paragraphs serialize lineExact=1600 hundredths of a point.
An earlier attempt used a removed old WASM-directory override and failed to load
WASM; this was an environment failure, not the valid behavioral RED. The valid
RED/GREEN runs used the existing installed-dependency WASM resolver.

Evidence: /tmp/pdf-pptx-text-geometry-20261111/{red-with-runtime.log,green.log,
fixed.pptx,receipt.json,ooxml-verification.json,download-ooxml.json}.
Actual fixed.pptx is 7783 bytes, SHA-256
8b5cb51a2dfd86f1a9363707c4b9dc9cadbc9c2e262a281c20c7f0299d2b3484.
Source complex-layout.pdf SHA-256:
6447bd9cbdbd5451979dd31773846c61e55c87d202012a59e7cb56b88ef987ba.
Independent OOXML read finds both 16pt column pitches and unchanged x/y offsets,
1 table, 1 picture, nine exact table cells and DejaVu Sans plus Liberation
Mono/Sans/Serif font names. No already-passed full suite was repeated.

## Independent host diagnostic render

The child sandbox isolates /dev/shm per tool call and cannot run LibreOffice
successfully. Its failed LO attempt produced no PDF and is not a pass. Root ran
the shared small diagnostic script /tmp/pdf-pptx-spacing-probe.py on the host,
placing all rendered PDFs and its LO profile under /dev/shm. Its read-back JSON
is /tmp/pdf-pptx-spacing-probe-root.json. The probe compared original output with
three isolated variants: lineExact=16 only, explicit paragraph indents=0 only,
and both. Original left/right LO pitches were 14.966997/15.222142pt. Setting
lineExact=16 produces 15.987287pt in both columns, within the 0.03pt tolerance.
Explicit marL/marR/indent=0 did not improve X positions and was NOT committed.

Absolute positioning remains unresolved. Both variants retain left/right X
36.793999/321.760986pt, versus source baseline X 32/317pt. Changing lineExact
moves the first baseline to 96.350708pt, versus source 90pt (original output
95.329712/95.584717pt). This change restores baseline-to-baseline rhythm but
does not certify absolute baseline placement or reduce every absolute position
error. Font substitutions and other renderer differences still require manual
review; overall validation remains false.

## Final artifact / browser handoff

The final native fixed.pptx above is distinct from diagnostic XML-edited variants.
Root rendered the actual browser-downloaded PPTX using host LibreOffice. Browser
download and independent OOXML evidence are in `/tmp/pdf-continue-pptx/summary.json`
and `/tmp/pdf-continue-pptx/independent.json`; the downloaded file is 7787 bytes,
SHA-256 `927cea3e02c0f1a2591d4015bee7421bc5e075ab2e736790e01fdcadeb071a8e`.
Host-rendered PDF SHA-256 is `8cbb297244f8018de574989a2dc625910c9d4830594f2b2713db8c043e441608`.
Verifier output `/tmp/pdf-continue-lo-verification.json` confirms both columns
render at 15.987pt pitch (within 0.03pt), the table has no false wrapping, and
the monospaced caption remains. Overall fidelity remains false: X offsets differ
by about 4.8pt and the first baseline by 6.35pt. Manual content/layout review is
still required.
Dedicated new smoke files use real grant/cookie/CSRF/packed-engine/publication
and signed PPTX download, with a complex fixture wrapper server. The runner
supports PDF_SMOKE_STATIC_DIRECTORY and REPORT_EDITOR_CHROMIUM_EXECUTABLE,
checks actual fetched asset identities, handles structured validation issues via
issue.message, and independently validates the downloaded OOXML. It performs
no LO rendering inside the browser test. Syntax checks and direct OOXML checks
passed; the browser has not been run by this child.

Host rendered-PDF verifier:
frontend/smoke/pdf-pptx-text-geometry-verify.py takes source PDF, actual PPTX,
LO-rendered PDF and optional --output JSON. It independently asserts eight
matching lines per column and every baseline step within 0.03pt of the source
16pt. It also checks the prior no-false-table-wrapping and Mono caption fixes,
and records remaining X/first-baseline errors with overallFidelityPassed=false.
