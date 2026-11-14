# PR #238 independent repair acceptance ledger

Date: 2026-11-14. This ledger records observed local executions; writing it did not rerun tests. No claim below substitutes the PR description's historical results for an independent run.

## Inputs and scope

- Original PR #238: `d421b911be0da8766a3285169a3da81a15c5331a`.
- Current code / merged #239: `1e4a0a344ffbd5b73f71c0a84bb67f766f19e8e9`.
- #239 source HEAD: `b25a50af6863403da2b8954d8749e0680f527b8d`.
- Read repository AGENTS.md and all three PR acceptance documents: NATIVE_PDF_SIGNATURE_FIELD_ACCEPTANCE.md, NATIVE_XLSX_SPLIT_PANE_ACCEPTANCE.md, NATIVE_WORD_TABLE_STYLE_ACCEPTANCE.md.
- Original combination tree: `ad55f52d9b85c588ba8252ffbc69acd61b6fc5b2`; automatic merge, no conflicts. All 46 PR #238 changed paths and all 15 #239 changed paths retained their respective source bytes; path intersection was empty. Config/lock projection was identical to original PR #238.
- Repair branch: `fix/pr238-merged-cells-paired-selection`, based directly on original PR #238, not a new remote PR.
- First two repairs: `ab4ad8c266d0927de48d0adb3ed4964d3c4eec28`, tree `9ae010d7adc7652e7cb6e405bdc4d5b1db9001a4`.
- ReadOnly repair and Python lint cleanup: `0d5c9d8eee150bdd580216a5308ce26a8cd5ef63`, tree `ccd0411e365958cc15822d639a6fd87e105f5bb8`; parent ab4ad8c preserved without rewriting.
- Final repair plus code combination tree: `7e1fdca47c1360dece3834dc6eb44f1314d2335c`, automatic merge, no conflicts. All 10 repair paths matched the tested repair HEAD; all 15 #239 paths remained byte-identical; configs/locks matched repair HEAD.

## Actual RED to GREEN

### Word physical merged-cell addressing

The original implementation iterated physical JSON children but addressed TableMap grid slots, which repeat cells for colspan/rowspan. Valid ProseMirror table fixtures with distinct per-cell fills reproduced this independently.

- Original implementation: colspan/rowspan x document style/look produced 4 failed; ordinary-table controls produced 2 passed; exit 1. Failure: the final consistency check raised the mixed-table-edit error. TableMap reported no fixture problems.
- Initial temporary filename: `src/review238-merged-style.red.test.ts`; final equivalent regression: `src/docx-table-style-merged.test.ts` (test names/imports cleaned; same behavioral checks).
- Minimal fix: use physical row and cell node offsets for setNodeMarkup, not repeated TableMap slots. Preserve cell contents and attributes.
- Repair branch: new six plus existing seven tests, 13 passed, exit 0, 10.50s.
- Combination tree `8ab04a306c1f0b61539281065118f4eb4f8b79a9`: same 13 plus #239 rail navigation five, 18 passed, exit 0, 16.85s.

### XLSX paired selection removal

- Original implementation with legal paired pane selection: 1 failed, exit 1; readback Saxes error `2:262: unexpected close tag`. Opening selection tag had been removed without its closing tag.
- Strengthened final paired fixture was also rerun against original split-pane.ts: 1 failed, exit 1, same Saxes failure; fixed bytes restored in finally.
- First repair passed paired selection, but a further case with a self-closing pane selection followed by an unrelated paired selection exposed greedy over-removal: 1 failed, 1 passed, exit 1. Failure specifically asserted preservation of the unrelated selection.
- Final minimal fix: consume self-closing or paired selection in full, using a non-greedy tail so following selections are not swallowed.
- Final new two cases plus existing two: 4 passed, exit 0, 2.09s. Checks include retained unrelated selection, zoomScale and byte-identical other ZIP entries.
- Final file: `bridge/split-pane-paired-selection.test.ts`.

### PDF direct and inherited ReadOnly signature fields

- Confirmed actual pdf-lib API: PDFField.isReadOnly -> AcroField.hasFlag -> Ff() -> getInheritableAttribute. Existing form-design.ts already rejects read-only fields.
- First fixture incorrectly encoded /T as PDFName instead of PDFString: 8 failures/errors from malformed fixture type. This is NOT a behavior RED and NOT counted as evidence of the production defect.
- Corrected valid direct/inherited flags fixtures: 6 failed, 2 passed, exit 1. Two inspect assertions observed bindable=true instead of false; four actual patchPdfWithReceipt ink/image calls lacked expected rejection. Writable unsigned ink/image controls passed.
- Minimal fix: add source?.isReadOnly() to inspectSignatureFields reason calculation. Existing server patch binding recomputes the model and rejects !field.bindable, so this is not only a picker restriction.
- Initially executed in temporary `bridge/signature-fields-readonly.test.ts`; then appended to existing `bridge/signature-fields.test.ts` so the enumerated default test script runs it. Fixture function renamed to readonlySource; shared PNG/imports reused.
- Final existing three plus new eight: 11 passed, exit 0, 1.71s. No /V written for normal successful visual signatures.
- Final combination selected smoke: direct/inherited ink refusals and writable ink success, 3 selected and passed, exit 0, 1.83s. Other nodes were not executed by this name-filtered run.
- LOCAL-SHA256.json updated for changed source/test; both digests independently checked. No lock changes.
- Coverage at code commit 0d5c9d8: writable control omitted Ff (default); explicit child Ff=0 overriding a read-only parent and a nonzero non-ReadOnly Ff were NOT tested at that stage. The supplementary run below closes these two specific gaps; the historical results above do not imply that coverage.

## Commands and separately observed results

All Python runs used `/workspace/sm/.venv/bin/python`; working root was `/workspace/review238`. The following are recorded runs, not new executions while writing this ledger.

| Working directory | Command | Result |
| --- | --- | --- |
| frontend | `node_modules/.bin/vitest run src/docx-table-style-merged.test.ts src/docx-table-style.test.ts src/slides-rail-navigation.test.ts` | 18 passed, exit 0, 16.85s on combination 8ab04a30 |
| workbook_engine | `node_modules/.bin/vitest run bridge/split-pane-paired-selection.test.ts bridge/split-pane.test.ts` | 4 passed, exit 0, 2.09s with final workbook source/test bytes |
| root | `python -m pytest smart_reporting/reporting/tests/test_native_word_task_builder_docx.py::test_actual_docx_builder_preserves_source_and_selects_only_authorized_paragraph -q` | 1 passed, exit 0, 27.71s on combination 8ab04a30 |
| pdf_engine | `node --import tsx --test bridge/signature-fields.test.ts` | 11 passed, exit 0, 1.71s, final repair bytes |
| pdf_engine, final combination | `node --import tsx --test --test-name-pattern='server refuses ink binding to.*ReadOnly\|server still binds ink' bridge/signature-fields.test.ts` | 3 selected passed, exit 0, 1.83s |
| root | `python -m pytest smart_reporting/reporting/tests/test_docx_native_table_style.py::test_table_style_gallery_and_look_options_with_independent_readback smart_reporting/reporting/tests/test_native_pdf_signature_field.py::test_signature_into_field_saves_associated_ink_and_reopens_as_signed smart_reporting/reporting/tests/test_native_xlsx_split_pane.py::test_split_pane_is_read_as_split_not_freeze_and_removed_with_readback -q` | 3 passed, exit 0, 26.72s, final repair bytes |
| frontend | `NODE_OPTIONS=--max-old-space-size=6144 node_modules/.bin/tsc --noEmit` | exit 0 on preceding combination 8ab04a30; final XLSX regex/test and later PDF changes were not re-typechecked in a second full run |

The filter command above uses a regex alternation `|`; the backslash in this Markdown table protects the column delimiter, not an extra literal shell escape.

Earlier independent original-combination scope: PDF bridge 3 passed; workbook bridge 2 passed; Python XLSX 7 passed; Python Word table style plus actual #239 DOCX positive 10 passed; frontend signature/table-style/rail 16 passed; split-window ribbon 1 passed with 55 name-unselected. These successes did not cover the three subsequently found edge defects.

Python PDF originally had 2 failures before feature assertions because slides_engine dependencies were absent (ERR_MODULE_NOT_FOUND @genoffice/agent-core); installed original locked dependencies and reran only those two: 2 passed, exit 0, 32.68s. No test assertions or repository locks were changed for environment setup. Python results retained the third-party visions/imghdr deprecation warning.

## Ruff, diffs, remote and boundaries

- New Python test cleanup only: two import-order corrections and two semicolon statement splits. All three affected files pass Ruff; corresponding three real roundtrip positives passed as listed above.
- Three previously verified baseline findings deliberately remain: native_office.py:2 I001; delivery/docx_native.py:2 I001; delivery/docx_native.py:82 UP017. The aggregate check of those production files exits 1 with exactly these three findings; do not claim all changed Python files pass Ruff.
- Final diff/cached diff checks passed; no unstaged production modifications. The full repair patch against d421b911 was saved outside the repository for review: 285 lines before this docs-only ledger, SHA256 `39e5494f319cc95e41e33bdb6caf6090aa5a4dc4649696ce0ceec862b909178c`.
- Remote original author activity was unknown. Repeated git ls-remote checks before changes, before/after each repair phase and immediately before this ledger all returned PR #238 d421b911 and code 1e4a0a34, with full SHAs above. No changed remote head was overwritten.
- Local only: no push (force or otherwise), new remote PR, remote merge, deployment, production service calls or production switches. Pending temporary integration was aborted before adding this ledger; code repair commits retained.
- Independent full-diff review remained pending when this ledger was written; do not imply reviewer approval or an executed merge. Remote PR still lacks these fixes.
- No full suite, GitHub CI, browser smoke, production build, Office/Acrobat manual verification, or real authorization/publication chain was rerun. Earlier PR acceptance documents are historical evidence, not executions in this repair round.


## Supplementary PDF flag override check and authorized branch update

- Independent reviewer subsequently read the complete 285-line repair diff and found the three repairs sufficient to close the reported issues, with no new Important finding. This is review evidence reported by the coordinating parent, not a claim that this agent performed that independent review.
- Verified PDF 32000-1:2008 section 12.7.3.1 and Tables 220/221 from the Adobe-hosted standard: inheritable attributes come from the parent only when not explicitly specified; Ff is an inheritable integer defaulting to zero; ReadOnly is bit position 1 and Required is position 2. Source: https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf . Web text extraction could not handle the file size; downloaded the same primary PDF to /tmp and read pdftotext output. This is whole-attribute inheritance, not bitwise OR across ancestors.
- Verified installed pdf-lib implementation: getInheritableAttribute visits the child before ancestors and retains the first PDF object found; a PDFNumber representing zero remains an object, so explicit zero is not skipped. Ff() resolves that object and getFlags()/hasFlag() inspect its bits.
- Extended real fixture with parent Ff=1 and child explicit Ff=0 or Ff=2. Four new cases: each child value with ink and image. Through actual inspectPdf -> patchPdfWithReceipt -> PDFDocument/patched model readback, assert binding succeeds, local child flags and parent flags remain unchanged, isReadOnly=false, Required reflects 0 versus 2, no V is written, the annotation associates Group.Signature, and reinspection reports visuallySigned=true.
- Retained default writable and inherited read-only controls. No production source change was necessary; these are compatibility checks that passed on first valid execution, not a new defect RED or a simulated RED.
- Command, pdf_engine directory: `node --import tsx --test --test-name-pattern='child Ff=|inherited ReadOnly signature field is advertised|server still binds ink' bridge/signature-fields.test.ts`.
- Observed result: 6 selected tests passed, 0 failed/cancelled/skipped, exit 0, 1.75s. Four are newly added override cases, two are existing controls; no full suite was rerun. An earlier command whose fixture-edit path was wrong executed only the two old controls; its two passes are not counted as the four new checks.
- Updated only the test checksum in LOCAL-SHA256; existing production checksum retained and checked. Repository locks and production sources remain unchanged from 0d5c9d8. Original three defect RED/GREEN evidence and both prior repair commits remain intact.
- Parent explicitly authorized a normal fast-forward push to existing PR branch claude/nice-franklin-3qpag8 only after this run and ledger update, conditional on re-fetching and observing PR/branch d421b911 and code 1e4a0a34 (full SHAs above). Independent review and that authorization do not themselves mean a push succeeded; the final tool result and coordinating parent must record the actual remote outcome.
- This supplementary change does not run or authorize remote merge, deployment, new PR, force push, production switches, full tests, CI, browser smoke or Office/Acrobat checks.
