# GenOffice slide engine

Vendored from `https://github.com/genspark-ai/genoffice` at commit
`f8c17004fb730df11f0f743164ffd8b4281bb38c`.

The integrated server packages are `agent-core`, `docx-engine`, `pipelines`,
`pptx-engine`, `pptx-ops`, `pptx-render`, and `zip-gate`, mapped directly from
upstream `packages/`. `docx-engine` remains a dependency of the existing engine;
native Word/PDF entry points are separate local integrations described in UPGRADE.md.

The source packages retain their Apache-2.0 license declarations. The upstream
`LICENSE` and `NOTICE` are included in this directory. The existing complete
`packages/pptx-engine/src/vendor/mtx/LICENSE` notice is preserved locally.

Local integration files are the root npm workspace/build configuration and lock,
`bridge/` request adapters, and `packages/pptx-render/src/browser.ts`, which only
exposes browser-safe exports. Bridges preserve artifact output before returning
layout-audit warnings; an audit exception is reported as an issue after writing
the file. These files are not replaced by upstream package updates.

The browser renderer adapter in
`../../report_editor/frontend/src/vendor/genoffice` is tracked separately with
its own source attribution, LICENSE and NOTICE.

Upgrade scope, local patches, verification commands and known typecheck limits
are recorded in `UPGRADE.md`.

Native DOCX bridge adapters reuse the upstream `pPrWithNumPr` and `pPrWithIndLeft`
helpers. Local `docx-engine` source adaptations against the pinned package
add exports to these two existing `generate.ts` functions (their implementations
are unchanged) and include `eastAsiaFont` in the run-font emission guard, so
clearing other font slots does not drop a remaining East Asian slot. See UPGRADE.md.
The `4b55db9` and `f8c17004` upstream
DOCX package trees are identical (`adc5c829f4cf3b5f7426541d784f0a7c61a6ae57`).
The bridge reports the common integration baseline `f8c17004` in `modelSource`.

2026-11-10 local DOCX adaptation: `Block.emptyRun` retains the source typing
format of paragraphs without visible runs. `parse.ts` reuses `buildRun` for
empty-run properties (last explicit property wins, paragraph-mark properties
override), without adding placeholder text to `Block.runs`. Paragraph styles
and document defaults remain inherited. The anchored native notes bridge uses
this source-only value when newly typed text inherits position zero.

2026-11-10 source-note typing adaptation: the existing note-reference parser
also reuses `buildRun(..., keepEmpty=true)` for the marker's complete Run format.
The original `rawRPr` and `noteRef` identity remain intact, and marker emission
still preserves the original XML. When typing inherits this trusted source Run,
the bridge removes only `noteRef` to create ordinary text. This avoids losing
managed properties such as superscript or run style during ordinary generation;
there is no second package parse or client-supplied raw XML.

SHA-256 of these locally adapted engine files:

| File | SHA-256 |
| --- | --- |
| `packages/docx-engine/src/parse.ts` | `89859d2c2d535c3e528c1da1fe1b87cfda7bc6d2a9caa65a2581da75ca13fe11` |
| `packages/docx-engine/src/types.ts` | `7264b0347fd95c1f6cf10e5a6dcef3f897d45d0fec007a25ff27c4d356ce56d0` |

2026-11-10 Native repeat-header adapter: bridge/docx-table-headers.ts uses the existing engine splitXmlChildren to patch direct table rows only. The strict setTableRepeatHeaders operation validates the source block hash, expected row count, boolean flags and selected leading prefix; it preserves other row/table properties, merged cells, nested XML and non-target package parts. No vendored engine file changes. See report_editor/NATIVE_WORD_TABLE_HEADERS_PLAN.md for fixed-source command attribution and acceptance evidence.

2026-11-10 Native CJK font extension: bridge/docx-font-slots.ts recognizes Ma Shan Zheng and ZCOOL XiaoWei as East Asian families (LXGW WenKai already recognized), matching the browser renderer local name patches. Only eastAsia changes; ascii/hAnsi/cs preserve existing values. Three OFL webfonts are hosted by the frontend, not embedded in DOCX.

2026-11-10 Native cell-shape adapter: bridge/docx-table-cell-shape.ts and strict reshapeTableCells use the shared PM mergeCells / pinned source splitCellsInto closure through report_editor/frontend/src/docx-table-cell-shape-core.ts. The adapter validates logical source grids, preserves original paragraphs and cell/row XML, patches only structural widths/spans, and verifies the actual saved DOCX. No docx-engine vendored file change. Host schema permits empty PM rows fully covered by rowspan. See report_editor/NATIVE_WORD_CELL_SHAPE_ACCEPTANCE.md for the scope, source attribution, regressions and built-browser evidence.

2026-11-10 Native column-width adapter: bridge/docx-table-column-width.ts and strict resizeTableColumns share report_editor/frontend/src/docx-table-column-width-core.ts and the pinned table-sizing.ts fitColumnWidths closure. The bridge derives the available width from the actual source section, validates logical merged geometry, changes only original gridCol/tblW/tcW width attribute values, and verifies saved XML. Integer-twip quantization retains odd totals; browser source normalization restores exact signed widths before the draft baseline. No docx-engine vendored file change. See report_editor/NATIVE_WORD_TABLE_COLUMN_WIDTH_ACCEPTANCE.md and its linked investigation for source attribution, evidence and remaining boundaries.

2026-11-10 Native row-height adapter: bridge/docx-table-row-height.ts and strict setTableRowHeights share report_editor/frontend/src/docx-table-row-height-core.ts. The source Ribbon selected logical row-band semantics are reproduced without copying its whole-table SavePlan generation. The adapter derives bounds from the actual source section, preserves source exact/atLeast rules, supports valid auto/zero source declarations, and patches only direct trHeight XML. Clearing keeps all other row/cell/paragraph XML; saved output is reread and verified. No docx-engine vendored file change. See report_editor/NATIVE_WORD_TABLE_ROW_HEIGHT_INVESTIGATION.md for immutable source attribution and the ongoing UI/built acceptance; DOM-measured row distribution is a separate outstanding item.

2026-11-10 Row-distribution protocol extension: setTableRowHeights also accepts the strict four-field distributeTableRows step. It forces atLeast and preserves a valid measured height up to 31680 twips even above the section text height; ordinary three-field set steps retain their section clamp. Ordered replay prevents an earlier exact rule from returning after distribution. The browser measures actual row DOM at temporary 100% zoom and restores display state; implementation and browser acceptance remain tracked in report_editor/NATIVE_WORD_DISTRIBUTE_ROW_HEIGHT_DESIGN.md.

2026-11-10 Native AutoFit adapter: bridge/docx-table-autofit.ts and strict setTableAutoFit share report_editor/frontend/src/docx-table-autofit-core.ts. Only fixedGridWidths is copied verbatim from pinned table-properties.ts; other mode behavior uses equivalent table projection, with trusted integer-twip input precision retained. Ordered contents/window/fixed steps patch only direct table/cell width, layout and grid geometry, preserve original content XML and reread actual saved geometry. The source whole-table SavePlan is deliberately not used because it loses paragraph XML attributes. Source investigation and ongoing acceptance: report_editor/NATIVE_WORD_TABLE_AUTOFIT_INVESTIGATION.md. No vendored docx-engine file changes.

2026-11-10 Native cell text-direction adapter: bridge/docx-table-cell-text-direction.ts and strict setTableCellTextDirection share report_editor/frontend/src/docx-table-cell-text-direction-core.ts. Equivalent selectedCells slot/owner semantics from pinned table-ops.ts update logical merged owners and all physical continuations, retaining untouched raw direction aliases and content. Horizontal clears only direct tcPr/textDirection; vertical modes modify only its value or insert the element. Saved XML and physical directions are reread and verified. No docx-engine vendored file change. See report_editor/NATIVE_WORD_TABLE_TEXT_DIRECTION_ACCEPTANCE.md for the current verification scope.

2026-11-10 Native cell-alignment adapter: bridge/docx-table-cell-alignment.ts and strict setTableCellAlignment share report_editor/frontend/src/docx-table-cell-alignment-core.ts. Equivalent selectedCells/setCellAlignment semantics from pinned table-ops.ts use existing vendor effectiveBidi/alignAttrFor; trusted parsed richParas reproduce converter paragraph type and explicit/inferred/style-inherited direction. Only selected owner direct pPr/jc and owner/physical-continuation tcPr/vAlign are patched; hidden continuation paragraphs, nested content, source geometry and other XML are retained. New properties follow source schema order, including retained cell revisions. Saved XML and semantic snapshots are reread and verified. No vendored docx-engine file change. See report_editor/NATIVE_WORD_TABLE_CELL_ALIGNMENT_INVESTIGATION.md for attribution and evidence; browser acceptance is tracked separately.

2026-11-10 DOCX ownership migration: packages/docx-engine, edit-docx/docx-* bridges and their tests/probes moved to sibling reporting/doc_engine. Historical DOCX entries above are retained as provenance; current DOCX ownership and build instructions are in ../doc_engine/SOURCE.md. PPTX equation and transition helpers continue to reuse the same DOCX math/XML modules through explicit sibling references, without duplicate sources.
