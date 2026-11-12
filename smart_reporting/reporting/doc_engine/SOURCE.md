# GenOffice DOCX engine

Dedicated DOCX integration, migrated on 2026-11-10 from sibling `slides_engine`.
Pinned source: `https://github.com/genspark-ai/genoffice`, ref
`f8c17004fb730df11f0f743164ffd8b4281bb38c` (Apache-2.0).

`packages/docx-engine`, `bridge/edit-docx.ts`, all `bridge/docx-*.ts`, and their
`bridge/tests/docx-*` files were moved with existing local adaptations intact.
The bridge entry point and output contract remain unchanged. This workspace
bundles only `edit-docx`; shared `pptx-engine`, `agent-core` and `zip-gate` are
file dependencies on the actual sibling `slides_engine/packages/` directories,
not copied forks. `LICENSE` and `NOTICE` retain upstream attribution.

The original SOURCE and UPGRADE evidence below is retained verbatim as historical
provenance. Statements describing DOCX as part of the old slides workspace refer
to its pre-migration layout; current DOCX package/bridge ownership is here.
Frontend host/vendor adaptations remain in `report_editor/frontend`; DOCX
investigation documents and test logs retain their original historical paths.

---

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
| `packages/docx-engine/src/parse.ts` | `85682e17eca59081a6d581782cec7df7b12c182379a60b2eb3738984ffde86f2` |
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


## Standalone migration validation (2026-11-10)

The independent workspace installs with npm install and lock-based npm ci
(`--ignore-scripts --no-audit --no-fund`); no shared package source was copied.
The three shared package links point to the sibling slides_engine tree. Package
source imports were checked: DOCX runtime code uses supported @genoffice package
entry points, with no broken ../pptx-engine relative imports after the move.
`npm run bundle:bridges` builds only dist/edit-docx.mjs. The resulting bundle
successfully inspected the real source fixture
`/tmp/cell-alignment-independent-review/unknown-ppr-run-field-source.docx`,
returning source SHA 907206c5b35003e6c69531efbf562e0cbd91a22eb4f4292b6cc60d6b50b61289
and one table block. Logs: /tmp/doc-engine-migration-inspect.log and
/tmp/doc-engine-migration-ci.log. No frontend build or full suite was run by this
migration subtask. Sibling workspace, Docker, Python and frontend path consumers
are updated by the root integration task; this paragraph does not claim those
external consumers are complete.

Migration consumer verification (2026-11-10): Python doc engine/env routing, frontend DOCX aliases/chunk identity, sibling PPTX math/XML consumers and Docker build/package/runtime selection updated. Doc and slides npm ci, independent bridge bundles, layout/Docker contracts, source-free DOCX patch and isolated PPTX/XLSX bridges passed. Cross-workspace license packaging now preserves frontend npm/vendor and sibling engine licenses without copying development sources. Unified frontend build and unchanged budget checks passed; 12 real browser DOCX save/download/reopen alignment cases used the independent DOC bridge. Full Word/XLSX parity remains open.

2026-11-10 Native table default cell-margins adapter: bridge/docx-table-cell-margins.ts and strict setTableCellMargins share report_editor/frontend/src/docx-table-cell-margins-core.ts. This implements the pinned Ribbon CellMarginsDialog table-default semantics; selected cell overrides/reset remain a separate Table Properties feature. Only direct tblPr/tblCellMar is patched in schema order. All physical tcMar, row/style exceptions, hidden continuation content and non-target XML/parts are retained. Signed snapshots distinguish effective defaults/cell overrides from raw explicit margin XML; source converter and actual saved XML are compared. Host UI stores integer twips and displays exact points, preserving unchanged fields rather than copying the source two-decimal-cm quantization. No vendored docx-engine file changes. Source attribution and tested boundaries: report_editor/NATIVE_WORD_TABLE_CELL_MARGINS_INVESTIGATION.md; browser acceptance tracked separately.

2026-11-10 Native selected-cell margin-override adapter: new host module bridge/docx-table-cell-margin-overrides.ts and strict setTableCellMarginOverrides share report_editor/frontend/src/docx-table-cell-margin-overrides-core.ts and its standalone project adapter. Logical rectangle/owner selection follows TablePropertiesDialog Cell-page setCellProps at pinned GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c. Ordered complete four-side integer-twip steps set direct tcMar; null removes the override on each selected owner and all physical continuations. Only direct tcPr/tcMar is patched, retaining hidden continuation paragraphs, source grid/rsid, direction, noWrap, other properties and non-target package parts. Raw owner declarations, owner raw-container presence, any-physical-override presence, effective PM margins and reset-effective PM margins are separate signed snapshots. The existing DOCX parser resolves original style/row inheritance using one cached batch reset/save/reparse per ParsedDocFull; client PM nonnull values are never treated as proof of explicit overrides. Ambiguous namespaces, revisions, legacy hMerge/gridGap and malformed geometry remain unsupported. No vendored docx-engine file or vendor hash change. Source-command and saved/reopened DOCX evidence, local parser-reference comparisons, narrow module tests and current limitations: report_editor/NATIVE_WORD_CELL_MARGIN_OVERRIDES_INVESTIGATION.md. Product build, HTTP and browser acceptance are tracked by the root integration task.

2026-11-10 Native row-break adapter: new host bridge/docx-table-row-breaks.ts and strict setTableRowBreaks share report_editor/frontend/src/docx-table-row-breaks-core.ts and its project adapter. Logical selectedRect row-band semantics follow pinned GenOffice f8c17004 TablePropertiesDialog rowPatchFor and table-ops.ts setRowProps. Ordered allowBreak booleans update entire selected rows; only direct trPr/cantSplit is inserted/replaced/removed. Empty paired and self-closing targets are handled without the pinned generator's paired-node removal defect. Source row flags and raw declarations are independently signed against the existing parser; source geometry, source row flags and actual saved XML are verified. Missing/self-closing trPr respects tblPrEx ordering, while row attributes, unknown non-target siblings, height/header settings, hidden continuation paragraphs and non-target package parts remain unchanged. This adapter uses the current parser's direct-row cantSplit behavior and does not extend Word table-style inheritance. Namespace ambiguity, property revisions, malformed merges/gridGap/hMerge and duplicate/invalid target controls remain unsupported. No vendored DOCX engine or vendor hash changes. Source-command probes, paired-node regression evidence and narrow-module verification: report_editor/NATIVE_WORD_TABLE_ROW_BREAKS_INVESTIGATION.md. UI/HTTP/browser and unified build acceptance remain with root integration.

2026-11-10 Native whole-table alignment adapter: new host bridge/docx-table-alignment.ts and strict setTableAlignment share report_editor/frontend/src/docx-table-alignment-core.ts and its project adapter. Pinned TablePropertiesDialog applyTableValue align semantics target the selected whole table: left removes direct tblPr/jc and projects reopened tblAlign=null; center/right set the corresponding direct value. Repeated same-kind edits replace the final native intent. Original paired/start/end jc declarations are signed separately from the parser's effective alignment; host UI preserves no-op aliases. Only direct jc is patched in CT_TblPr order, retaining tblInd (including negative, zero, paired and opaque unit declarations), tblW/grid/tcW, floating positions, unknown siblings and hidden continuation paragraphs. Floating or suppressed-floating source remains editable for jc and is reported by signed positioning='floating', allowing the UI to explain that positioning takes precedence and remains unchanged. This adapter uses existing parser/renderer RTL and style semantics; it does not add left-indent editing or redefine physical/logical RTL alignment. Namespace ambiguity, property revisions, duplicate/invalid target controls and malformed merged grids remain unsupported. No vendored engine or vendor hash changes. Fixed-source commands, actual save/reparse probes, local narrow tests and boundaries: report_editor/NATIVE_WORD_TABLE_ALIGNMENT_INDENT_INVESTIGATION.md. Product/UI/HTTP acceptance is handled by root integration.

2026-11-10 Native cell wrap adapter: bridge/docx-table-cell-wrap.ts with frontend docx-table-cell-wrap-core.ts implements pinned GenOffice direct noWrap semantics (see NATIVE_WORD_CELL_WRAP_INVESTIGATION.md). Strict setTableCellWrap accepts ordered logical rectangle/wrap steps, patches every physical owner/continuation without rebuilding cells, and preserves hidden text, tcFitText, unknown siblings and unrelated ZIP parts. It does not implement Word style inheritance or fit-text. Fixed/overwide layouts may still wrap visually. Python hash/protection/batch validation, exact collector/replay and actual saved parser verification are required; browser acceptance is tracked separately.

2026-11-10 table alternative-text numeric-reference parser adaptation: only
`attachRawTablePr` caption/description values are reread from their direct raw
property attributes using the existing `decodeEntities` helper (numeric references
before named entities). This preserves real LF/CR/TAB references and keeps literal
`&amp;#10;` as visible `&#10;`, avoiding a second decode after parsed tree attributes
have lost the escape provenance. No other parsed table fields or XML are changed.
The independent `bridge/docx-table-alt-text.ts` adapter patches only direct
tblCaption/tblDescription and emits whitespace character references. Frontend
core/project preserve content and use a dedicated final-value intent; strict
length/XML-character limits are host boundaries. Fixed source remains GenOffice
`f8c17004fb730df11f0f743164ffd8b4281bb38c`, TablePropertiesDialog commitAlt,
editor/table-properties updateSelectedTableAttrs and engine generateTableModelXml.

2026-11-11 Native page-colour adapter: bridge/docx-page-color.ts exposes the document background (none or a single plain w:color) with its source digest; the strict setPageColor operation is validated batch-first and passed to the unchanged pinned saveDocx pageColor option (w:background + settings w:displayBackgroundShape), then read back from the output parts. Theme-colour, VML-fill, duplicate and protected sources stay read-only. Fixed source: Design ▸ Page Color (ribbon-design-tab.tsx onPageColor / RibbonColorPalette).
