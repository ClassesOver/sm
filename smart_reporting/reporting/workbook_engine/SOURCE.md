# Workbook engine source

## 2026-11-11 owned control field identity migration

Named-source field renames now allow complete owned native slicers and timelines.
The field planner accepts a full byte snapshot for this path; table edits create
it from the current ZIP overlay so consecutive edits use current identities.
The frontend preflights the same bytes and identity plan. Existing control
validation runs before and after migration. Control definitions, sourceName and
default fallback captions follow their field names; explicit captions, member
selection, timeline intervals, typed dates, geometry and relationships survive.
No output or cache-record rebuild is part of a rename. The standard cache reader
only permits the exact known timeline extension when a validated associated
timeline exists; arbitrary extensions remain unsupported.

Control parts must have exclusive incoming relationships, checked even during
the identity preflight. This shares the deletion guard and uses the existing
namespace-aware relationship parser, covering paired/self-closing elements,
attribute quotes/spacing, prefixes, escaped targets and comment decoys. Unknown
controls, incomplete pivot state, stale shapes and field removal remain guarded.
This remains a local implementation with no desktop Excel certification.

## 2026-11-11 owned named-source field rename

Local `pivot-source-field-rename.ts` extends the dependency guard below only for
complete owned pivots with unchanged source column count and physical positions,
in workbooks without native slicers/timelines. `table-edit.ts` applies the planned
standard cache names/formulas and raw private-state changes in the same ZIP
overlay. Existing formula ASTs perform simultaneous renames, including swaps;
unknown private metadata survives. Group/filter indices, cache records and output
remain unchanged until an explicit refresh. Every related cache owner and workbook
registration must agree; all relationships are checked before excluding an owner.
Imported/incomplete state, native controls, field removal or stale source shape
remain guarded. Attribute replacement handles legal quotes/spacing and preserves
decoy attribute text, followed by semantic validation of actual target names and
formulas. This is a local adaptation, not an upstream or desktop Excel claim.
Hashes are pinned in `UPSTREAM-PATCHES-SHA256.json`; integration regressions live
in `frontend/src/workbook-pivot-field-rename.test.ts`.

## 2026-11-11 named pivot source field dependency guard

Local table edits reject renaming/removing fields still present in a dynamic
pivot's standard cache or persisted source-field state. Changes compare the
original physical columns, including cyclic header renames and left-edge
resizes. Cache matching validates complete namespace-aware XML, handles entities,
case variants, imported ST_Xstring escapes and legacy local literal `_xNNNN_`
names. Fields added after the cache snapshot remain editable/removable. This is
a dependency safeguard, not field-identity migration or automatic cache refresh.
Frontend guards use original table identities so another table reusing a draft's
old source name is not mistaken for a consumer.

## 2026-11-11 named pivot source table headers

Local `table-edit.ts` checks dynamic pivot dependencies before disabling a source
table's header row, reusing the cache/private-state dependency guard. Rejection
leaves the input package unchanged, including for imported standard pivots and
same-transaction source renames. Ordinary tables and fixed-range pivot sources
retain their existing header controls. The frontend previews the complete draft
through this engine before clearing native header cells; this is a local
integration safeguard, not an upstream or desktop Excel certification.

## 2026-11-11 named pivot source table rename

Local table edits migrate matching named worksheet cache sources together with
validated owned pivot state, without recalculating records, output, filters or
native controls. Standard imported pivots retain their original definition.
Conversion to a range is refused while a pivot still depends on the table;
external or inconsistent source identities are not rewritten. The existing
namespace-aware cache source scanner is shared with sheet renames. Source and
targeted regression hashes are recorded in `UPSTREAM-PATCHES-SHA256.json`.

## 2026-11-11 named pivot source table identity

Local `pivot-add.ts` resolves `sourceTableName` against table `name` and
`displayName` without case sensitivity, consistently with the existing table
editor. Creation and relayout retain the actual table name in standard cache
source XML and the local persisted pivot state. Existing missing-table,
single-header-row and read-only table guards remain in force. The current local
file is pinned in `UPSTREAM-PATCHES-SHA256.json`; this is a local correction,
not an upstream source-byte claim. Frontend creation/import/refresh and direct
save-operation regressions live in `frontend/src/workbook-pivot-table-source.test.ts`.

2026-11-10 表格编辑前置：`src/table-edit.ts` 改编固定源
`f8c17004fb730df11f0f743164ffd8b4281bb38c` 的
`packages/xlsx-gateway/src/gateway/xlsx-table-edit.ts`，复用本地 ZIP overlay
与严格表格关系读取，提供 browser-safe `applyTableEdits`。接口按工作表名和
表名定位，不接受调用者注入 part 路径。保留列扩展/身份、关系命名空间和
非目标部件；转换区域清理同表别名，跨表共享 table part 拒绝改写。
元数据 API 本身不改表头单元格或公式；编辑器负责同批提交单元格和引用迁移。
新增/修改源码与测试已登记 UPSTREAM-PATCHES-SHA256.json；桥接与 UI
不属于引擎来源哈希范围。完整 Table Design UI 和原生样式渲染尚未交付。

Vendored from local sheets-web/packages/xlsx-engine, package @sheets-web/xlsx-engine 0.1.0, on 2026-11-03. The supplied sheets-web checkout has no committed HEAD; SOURCE-SHA256.json pins the exact source snapshot. Upstream provenance (genoffice f5247d3 and later local extensions) is preserved in UPSTREAM.md. License: Apache-2.0, as declared by sheets-web and its package manifests.

Only this engine and its tests are migrated. Node bridge and report integration are smart_reporting additions. Browser and server import this same package. No runtime dependency on adjacent sheets-web sources.

The local static report image extension in `src/chart-add.ts` reuses the existing drawing, anchor, relationship, and package pipeline. `LOCAL-ADAPTATIONS-SHA256.json` pins the modified engine file. Server-only file identity checks are in `bridge/images.ts`.


## 2026-11-05 selective upstream maintenance

Reviewed GenOffice `4b55db9ed1994575a695160ffc6cfd0bfc866211` (2026-11-04 snapshot). The engine remains the sheets-web browser-safe subset, with three upstream fixes backported: Excel 1900 serial-date grouping (`92ab9c46`), numeric text in baked pivot aggregates/calculated fields (`17cd6e4a`), and deterministic non-finite sort keys (`69880bc8`). See UPSTREAM.md for scope and exclusions. This is not a replacement with the complete latest `@genoffice/xlsx-gateway`.

SOURCE-SHA256.json retains the original migrated sheets-web snapshot. LOCAL-ADAPTATIONS-SHA256.json records the adapted package manifest. UPSTREAM-PATCHES-SHA256.json pins the files changed or added by selective upstream maintenance and the local native notes/filter integration described below. Apply the manifests in that order; later entries take precedence. Together they cover every file under packages/xlsx-engine (98 files), not the local bridge, root toolchain, documentation, LICENSE/NOTICE, or the hash manifests themselves. The exclusions are not upstream source claims. The manifests do not imply that unported upstream features are present.

Latest review: `f8c17004fb730df11f0f743164ffd8b4281bb38c` (2026-11-05). The additional six upstream commits add desktop external-link break/retarget, formula-settle export and printing features; those depend on desktop/Rust gateway modules absent from this browser-safe subset. They are not claimed as integrated. Existing three backports remain unchanged.

## 2026-11-06 local native notes integration

`note-read.ts`, `notes.ts`, `workbook-read.ts`, `sheet-ops.ts` and the package exports add a local adapter for plain legacy cell notes. This is smart_reporting integration, not a claim that these bytes match upstream. The existing whole-sheet `applySheetNotes` API remains available; `patchSheetNotes` verifies a source identity and patches only changed cells, retaining source authors, untouched comment nodes and foreign VML shapes. Unsupported threaded, rich or image-backed note sources are preserved but are not exposed as editable plain notes.

Row/column insertions and deletions now migrate note references, VML Row/Column/Anchor coordinates and deleted-note package relationships atomically with worksheet geometry. The added `tests/notes-structure.test.ts` covers adjacent notes, boundary rejection, independent openpyxl fixtures, foreign shapes, existing Pict-only VML and last-note cleanup. `tests/notes.test.ts` and the new reader are included in the later hash manifest. Range sorting, drag moves, threaded comments, note pictures and persisted popup visibility are not covered by this adapter; no feature-parity claim follows from hash verification.

## 2026-11-07 server sort and sheet filter integration

`sheet-ops.ts` adds `sortRangeRows` for the server/AI-tool path: the raw `<c>` records inside the range are permuted at the worksheet-XML level, so values, type markers and style indexes travel with their row (matching the official grid reorder) while row attributes stay in place. Ranges containing formulas or notes fail closed with explicit reasons; the bridge `sortRange` case now routes there (`tests/sort-rows.test.ts`).

`filter-read.ts` and `filters.ts` add a local adapter for plain worksheet-level auto filters: the first sheet-level `<autoFilter>` (customSheetViews copies ignored) is read into the workbook model with values/blank and custom-filter columns, and `applySheetFilter` writes or clears the element declaratively together with row visibility, rejecting unsupported conditions (color/icon/dateGroup/top10/dynamic), table overlaps and contradictory requests without touching the bytes. Column insert/remove shifts the filter ref and rebases filterColumn offsets; row insert/remove shifts the ref. Threaded into the bridge as `applySheetFilter` (`tests/filters.test.ts`, `test_workbook_legacy_filter_cli.py`). dateGroup/color/top10/dynamic conditions remain read-refused; table-scope filter routing and calendarType preservation are not implemented.

2026-11-09 `applyRowHeights` accepts `heightPoints: null` to return a row to
automatic height (drops `ht`/`customHeight` on the row element, cells and other
attributes kept; rows the file never sized are left alone). Used by the editor's
AutoFit Row Height. `src/geometry.ts` and `tests/geometry.test.ts` are pinned in
UPSTREAM-PATCHES-SHA256.json.

2026-11-09 `applySheetEdits` writes new `<sheet>` elements with their own
`xmlns:r` declaration. openpyxl binds the relationships prefix per `<sheet>`
rather than on `<workbook>`, so an added sheet without it left `r:id` unbound
and the whole workbook unreadable. `src/sheets-edit.ts` is pinned in
UPSTREAM-PATCHES-SHA256.json.

2026-11-09 `applyCellShift` (new `src/cell-shift.ts`, local addition: GenOffice
f8c17004 Insert/Delete Cells serializes its whole Univer model, so there is no
engine op to port) inserts or deletes a cell range shifting right/down/left/up.
It is a banded structural op: `ShiftSpec.band` (`src/structural.ts`) limits the
shift to the selected rows/columns and leaves references whose cross-axis extent
is not wholly inside the band as written (whole-row/column spans included);
`src/notes.ts` keeps notes outside the band in place. Cells move with their
records, row elements stay; same-sheet formulas, qualified formulas on other
sheets, defined names, chart series and notes follow; merges shift only when
wholly inside the band. Tables, autoFilter, validations, conditional formats,
hyperlinks, drawing/OLE/control anchors and shared/array formula groups that
touch the shifted region, merges straddling the band or split by a delete, and
values pushed off the sheet are refused. `src/sheet-ops.ts` exports
`sheetPartsOf`. `src/cell-shift.ts`, `src/structural.ts`, `src/notes.ts`,
`src/sheet-ops.ts`, `src/index.ts` and `tests/cell-shift.test.ts` are pinned in
UPSTREAM-PATCHES-SHA256.json.

2026-11-09 protection readback (new `src/protection-read.ts`, local addition):
`readWorkbook` projects `SheetModel.protection` (`<sheetProtection sheet>` and
whether a password/hash guards it) and `WorkbookModel.workbookProtection`
(`lockStructure` and workbook password). The editor's Review ▸ Protect Sheet /
Protect Workbook toggle only what `protection.ts` writes (password-less) and
leave password-protected targets read-only. `src/protection-read.ts`,
`src/workbook-read.ts`, `src/index.ts` and `tests/protection-read.test.ts` are
pinned in UPSTREAM-PATCHES-SHA256.json.

2026-11-09 `readWorkbook` projects `SheetModel.showFormulas` (sheetView
`showFormulas`, present only when true) so the editor's Formulas ▸ Show
Formulas starts from the file and its save diff writes only changes through
the existing `applyPageSetups` `showFormulas` field. `src/workbook-read.ts`
and `tests/show-formulas.test.ts` are pinned in UPSTREAM-PATCHES-SHA256.json.

2026-11-09 native data validation: `src/data-validation.ts` ports the pinned
GenOffice `packages/xlsx-gateway/src/gateway/xlsx-dv.ts` writer, replacing only
its grid-bound import with the same constants. Local `data-validation-read.ts`
and `data-validation-write.ts` project legacy/x14 rules and replace only a fully
modeled worksheet rule set. Unknown container/rule metadata remains read-only.
`workbook-read.ts` exposes the model. Structural row/column edits update legacy
and x14 rule targets, formula references, counts and empty DV extensions;
`sheets-edit.ts` also renames x14 formula sources. Their files and the writer/reader
tests are pinned in UPSTREAM-PATCHES-SHA256.json. The bridge and Python native
operation whitelist expose replaceSheetDataValidations; the old append API is
unchanged. Full frontend evidence and limitations are in
../../report_editor/NATIVE_XLSX_DATA_VALIDATION_ACCEPTANCE.md.

## 2026-11-09 table context adapter

`src/table-read.ts` exposes worksheet-owned table metadata through
`SheetModel.tables`: package path, table/display name, zero-based range,
header/totals row counts, decoded column identities and style options.
This is a local adapter using existing ZIP/XML/XLSX escape helpers, not an
upstream byte-for-byte migration. It follows only explicit tableParts and
internal table relationships; malformed/incomplete or foreign contexts return
an empty table list with tablesReadOnlyReason while retaining workbook access.
It does not yet project official table resources, enable Table Design or
implement table edits. See tests/table-read.test.ts.

2026-11-10 header-row alignment: TableAddition accepts optional headerRow=false to persist the actual headerless range directly, including a single data row. Such tables emit headerRowCount=0 and omit autoFilter; default creation retains its existing header/filter behavior. No worksheet cells are rewritten by table addition. UPSTREAM-PATCHES-SHA256 records the updated table-add.ts.


2026-11-10 local defined-name scopes: `src/defined-names.ts` and
`src/workbook-read.ts` project `localSheetId` through stable sheet names,
allow same-named global/local entries, and preserve reserved `_xlnm.*` and
opaque invalid scope ordinals. `src/sheets-edit.ts` updates valid scope indices
on reorder/removal while retaining unknown indices. `src/structural.ts` shifts
unqualified references only for the owning local scope, decoding XML sheet
names before matching. This is a local adapter; no upstream complete-parity
claim follows. `tests/defined-names.test.ts` and these sources are pinned in
UPSTREAM-PATCHES-SHA256.json. Native editor scope/structural regressions and
independent openpyxl bridge tests cover the live/save consumers.


2026-11-10 table filter-button projection: `src/table-read.ts` exposes whether
a headered table owns an autoFilter. This local projection feeds the editor's
filter-button state; `src/table-edit.ts` already follows the pinned GenOffice
writer: disabling removes the filter and its criteria, enabling creates a
filter over header/data excluding totals, and headerless tables omit filters.
`tests/table-filter-button.test.ts` verifies those semantics and unchanged
worksheet/package parts. The reader and test are pinned in
UPSTREAM-PATCHES-SHA256.json. The editor reuses official table filter events
and undo history; no general OOXML filter-criteria editing claim follows.

2026-11-10 existing custom table-style DXF display: `src/table-style-read.ts`
ports the pinned native `table_styles.rs` palette projection, resolving stored
DXF fill/font colors, theme tints, indexed colors, gradient midpoint, band
colors and borders. `src/workbook-read.ts` attaches the matching source style
to table models; editor theme metadata retains it across option/header/totals
rebuilds. No custom-style authoring or styles.xml rewriting was added. The
renderer preserves the source precedence: explicit fills/fonts survive; table
border edges override the corresponding cell edges. Source palette, real
Univer cell composition, undo/redo, and unchanged ZIP entry bytes are covered
by focused tests; this does not claim all OOXML DXF features are supported.

## 2026-11-10 outline grouping

Selectively aligned GenOffice f8c17004 `data-tools-actions.ts::handleOutline`, `outline-model.ts`, and `outline-actions.ts`: row/column levels 0–7, nested collapse/expand, summary-line collapsed attributes, source-style non-undoable level edits, and native undoable visibility. Local `outline.ts` surgically writes row/column outline metadata and visibility, preserving unrelated axis properties; `workbook-read.ts` exposes imported levels, flags, and summary placement. Bridge `applySheetOutline` uses strict bounded index/level schemas. The browser adapter uses native axis custom metadata so structural edits carry identity; inserted interior detail inherits the minimum adjacent level. Frontend grouping actions and ZIP/Python tests do not imply outline gutter rendering or subtotal support.

2026-11-10 remaining outline actions: the editor now exposes explicit row/column hide/show, Clear Outline (single-cell or absent selection clears the sheet), summaryBelow/summaryRight placement toggles, and source-gated Shift+Alt+ArrowLeft/Right grouping shortcuts. `src/outline.ts` patches optional boolean summary placement in worksheet sheetPr/outlinePr while preserving existing properties and other ZIP entries; the strict bridge and Python adapter accept summary-only edits without breaking existing row/column operations. New focused tests cover real Univer metadata, exact group identity, level-button shared-summary flags, nested explicit folds, summary-boundary guards, ZIP preservation, and native Python/TS/openpyxl roundtrips. Gutter adapters consume these APIs to read actual raw visibility, toggle one exact current group, and show a chosen level; their rendering acceptance is tracked with the frontend integration. Subtotals and complete OOXML outline parity remain outside this delta. Undo-triggered insert mutations preserve both explicit-zero and metadata-absent source gaps rather than inheriting neighbouring levels.

2026-11-10 outline reader module boundary: `src/outline-read.ts` mechanically extracts worksheet summary placement and row/column outlineLevel/collapsed attribute reads from `src/workbook-read.ts`. It imports only the pure XML helper, keeping the existing read behavior and avoiding a dependency cycle through the outline writer. The browser can assign this reader to the outline chunk; no budget threshold or file semantics changed. Real ZIP outline read/write regressions pass before and after the extraction. Both reader files are pinned in UPSTREAM-PATCHES-SHA256.json.


## 2026-11-10 modern formula storage marker reader

The writer already restores Excel `_xlfn.` / `_xlws.` markers but the browser reader did not remove them, causing MINIFS/MAXIFS saved by this engine to recalculate as #NAME?. The fixed GenOffice gateway TS reader likewise depends on its sidecar for normalization; this is an explicit local browser-without-sidecar adaptation, not an assertion that the upstream TS reader performs it. `withoutFutureFunctionMarkers` reuses token-scanning ideas from fixed-ref gateway/future-functions.ts and renderer/formula-functions.ts, skips quoted strings/sheet names and bracketed structured references, and strips only call-token storage prefixes. The local bracket skip additionally respects apostrophe-escaped brackets after an independent RED case. Existing writer behavior is retained. Sixteen real-ZIP cases pass, with related CSV checks; see NATIVE_XLSX_FUTURE_MARKER_READER_ACCEPTANCE.md. Changed files are pinned in UPSTREAM-PATCHES-SHA256.json.

## 2026-11-10 Univer checkbox validation persistence

The pinned GenOffice f8c17004 ribbon calls `newDataValidation().requireCheckbox()`;
its gateway saves the numeric 1/0 or custom-value rule as an Excel list fallback.
The local `checkbox-validation.ts` explicitly preserves the editor type in a
versioned worksheet extension (`urn:smart-reporting:xlsx:checkbox:1`), while
retaining that source fallback. This is a local browser persistence adapter,
not an upstream feature or Excel's modern boolean cell-control format.
The reader restores only a unique metadata/fallback pair whose complete
canonical rule (ranges, formula values and options) matches the actual DV.
Invalid, stale, duplicate or foreign metadata is ignored without dropping the
ordinary DV. Append validates previous identities before carrying metadata
forward and removes metadata for replaced/deleted ranges. Other extensions
are retained. No heuristic converts an ordinary 1,0 list into a checkbox.
The native browser helper uses Univer's real checkbox widget and undo history.
Independent Python patch/openpyxl/ZIP checks retain numeric values and other
parts. Reading with openpyxl can warn about the unknown extension; saving via
third-party tools may discard it and leave the compatible list fallback.

2026-11-10 headings reader alignment: `workbook-read.ts` now exposes the sheetView `showRowColHeaders` state as `showHeadings`, defaulting to true and accepting OOXML false/0. The existing page-setup writer already writes this state. A focused real-ZIP write/read/restore test covers the new reader field; browser control and end-to-end persistence remain separately verified by the native editor, not implied by this reader change. Files are pinned in UPSTREAM-PATCHES-SHA256.json.

## Native full conditional-formatting snapshots (2026-11-10)

The new source serializer, browser reader, schema and package snapshot adapter
are described in CONDITIONAL_FORMATTING_SOURCE.md. The serializer is an exact
copy of fixed GenOffice f8c17004 gateway/xlsx-cf.ts; source and local SHA256 are
recorded there. Index and workbook-read expose the complete native rule model
without replacing the legacy narrow conditionalFormats render projection.
The old append API remains compatible. New per-sheet replacement operation,
including clear-to-empty, is replaceSheetConditionalFormats. Package files and
tests are pinned in UPSTREAM-PATCHES-SHA256.json. Bridge operations, dedicated
CF/outline regressions and local provenance are pinned separately in
CONDITIONAL_FORMATTING_LOCAL_SHA256.json; these are local glue, not a claim
that bridge files came from upstream. Outline optional-field normalization
preserves false values without relaxing validation. No publication/download
path is changed. The unchanged old readWorkbook stylesheet requirement still
needs a later default-style fallback for packages without styles.xml; writer
coverage alone does not prove that complete browser workflow.

The public missing-styles reader gap described above was subsequently resolved:
fixed-source read_styles semantics now yield one empty default style for the
optional absent part, with no fabricated font/size/color and no ZIP write.
The complete CF reader also accepts any valid ARGB alpha prefix, following
fixed-source resolve_color; canonicalization changes only valid color rgb
attributes. Real 00/80/FF alpha and no-styles fixtures plus unknown-property,
missing-dxf and malformed-color boundaries are covered by targeted tests.
Updated reader/test identities are pinned in UPSTREAM-PATCHES-SHA256.json.

Theme/indexed/tint differential colors now reuse the existing table-style reader's
exported createStylesheetColorResolver, including custom indexed palettes and
system slots 64/65. The source resolver retains theme-over-RGB precedence.
Unknown attributes, unresolved themes, invalid tint/indexed values remain
incomplete. Exact unchanged wire identities retain their original dxf IDs,
including distinct themes that resolve to the same RGB; a real style edit
interns a new differential style instead of rewriting source theme definitions.
The shared resolver extraction preserves table-style behavior (six affected
regressions pass). The callback captures its foreground-presence boolean before
replacement so both engine and frontend strict TypeScript configurations narrow
optional XML safely, without a non-null assertion.

Linked CF structural scope repair (local deviation from fixed source): fixed
xlsx-structure.ts:1562 shifts only the base conditionalFormatting sqref. The
local structural.ts now verifies a unique x14:id/twin id, identical source
sqref/type/priority, and standard x14/xm namespaces before moving that twin's
xm:sqref. Deleting the whole scope removes both base and twin, the empty known
CF container/extension, and an empty extLst; unrelated extensions remain raw.
Ambiguous linked identities refuse only the structural edit. Multiple rules
sharing a base scope keep their original conditions. No wire fields changed.
Eight new cases first failed against the prior implementation, then passed,
including actual ZIP insert/remove/read-back and byte-identical unrelated sheet.
Two additional empty-wrapper/mixed-base cases and three existing ranged-feature
regressions pass. Evidence: /tmp/cf-linked-structure-red.log,
/tmp/cf-linked-structure-first-green.log, /tmp/cf-linked-structure-extra.log,
/tmp/cf-linked-structure-regression.log. Engine and bridge typecheck exit 0 in
/tmp/cf-linked-structure-types.log. CellIs reference parity remains a known RED;
its incomplete next-stage implementation is parked outside the repository.

CellIs reference/text/blank projection (local fixed-renderer adaptation):
conditional-formatting-read.ts now follows univer-sync.ts:7481
cellIsBlankDiverges, :7517 buildCellIsFormula and :7689
buildCellIsNonNumeric. Native number comparisons remain native unless blank
behavior differs within the source 20,000-covered-cell formula budget.
Nonnumeric comparisons retain operand parentheses; quoted equality uses the
source wildcard escape and case-insensitive formula, with the same huge-range
native-text fallback. Disjoint ranges use the source top-left-sorted anchor
and summed coverage. Unsupported arity/operator/mixed numeric-between cases
remain explicit incomplete snapshots. Wire formulas omit '=', as existing
expression wire does; frontend formulaShape already adds it for Univer.

The raw cellIs XML is first verified against the fixed source serializer's
number-rule shape with exact original formulas restored for identity checking.
Only after that check is the source renderer projection applied. Persistence
recomputes matching condition/ranges from the actual ZIP, retains raw cellIs
condition XML on unchanged or style-only edits, and writes expression only
when the condition changes. Unchanged whole snapshots retain original ZIP
bytes; unchanged rules beside other edits retain original XML attributes and
formula spelling (apart from a necessary priority change). Same-condition
rules prefer exact complete/style identities when recovering raw conditions,
so reordered differential styles do not swap. No client raw/provenance field
is trusted, and linked full-wire checks remain unchanged.

Evidence: /tmp/cf-cellis-source-contracts.log (37 new source contracts),
/tmp/cf-cellis-complete-targeted.log (100 reader/snapshot + 12 bridge tests
passed before the final attribute-preservation case), and
/tmp/cf-cellis-preservation-final.log (three final preservation cases passed).
The original reference RED is now GREEN. The source serializer SHA remains
 db38a4ca48933595db8019acce5f45b27f1fdff2f01d43bd6ae7abd84b16e18e.
A separate real-source oracle extracted six unchanged functions from fixed
univer-sync.ts via TypeScript AST and executed them in a VM: 636 supported
combinations matched the local projection, including all operators, numeric
blank behavior, text/wildcards, expressions and 3/20,000/20,001 cell budgets.
Probe: /tmp/cf-cellis-source-oracle.mts; result:
/tmp/cf-cellis-source-oracle.log. Extracted-functions SHA256:
771cee64d5c48b941949a69b9e1acff6a3dfc1e2c054145fc232c51869c971be.

Shared structural CF partition stage: conditional-formatting-structure.ts is a
local pure interval planner. It splits coverage at formula reference transition
boundaries (including absolute/mixed axes, copy/fill off-grid transitions,
whole-row/column references and band edges), never enumerates cells, caps
rectangle multiplication before loops, preserves original parent priority slots
and reanchors each formula tuple to its own sorted group. Geometry shifts only
on the edited host sheet; cross-sheet dependencies transform without moving
host coverage. Adjacent equivalent pieces merge. Full-grid axes stay in bounds
and preserve inserted full-axis coverage. Lowercase references use the same
case-insensitive convention as fixed-source offset/structural transforms.

conditional-formatting-offset-source.ts extracts unchanged copy/fill functions
and constants from fixed domain/formula-shift.ts; only imports/grid constants/
RefPart plumbing are adapted. Full original file SHA256: cf1df9b29f0ab58607b4ba38b7ce6851232bdb649c9a69c24bde603e320d5360.
conditional-formatting-structure-xml.ts derives groups only from actual ZIP XML,
retains raw dxf IDs/attributes, clones source-verified linked twins with unique
IDs and matching scope/priority/formula tuples, preserves extension-only visual
fields and unrelated extension bytes. Final exported rules are checked for
exact semantic identity against the pure plan (not merely issue/count checks).
applyRowColumnOps reuses that planner for every affected rule sheet and journal
operation. Incomplete legacy CF retains its previous range-only contract and
never gains editable complete status. applyCellShift still retains its previous
intersecting-CF refusal; the pure/XML band APIs are tested but the cell-shift UI
pipeline is a separate integration boundary, not silently claimed complete.

This corrects specific upstream behavior: official dependency-only splits were
observed moving host coverage to B2:B5 and Add siblings unshifted above a higher
stopIfTrue rule; fixed gateway structural formulas omitted CF formula bodies.
The local frontend and file replay now share ordered partitions; no client
provenance fields authorize linked changes. Source writer remains byte-identical.
Evidence: tests/conditional-formatting-split.test.ts real ZIP cross-sheet insert,
delete REF partition, whole-column boundedness, mixed absolute axes, disjoint
anchors, all formula thresholds, linked derived pairs and extension visuals,
quoted literals/sheets, band coverage, preloop partition budget, lowercase refs;
/tmp/cf-split-final-green.log and /tmp/cf-split-final-types.log record final
engine evidence. Frontend owns native mutation history and its GUI acceptance.

Cell-shift CF stage now implements the previously explicit refused boundary.
Both pure planner and trusted XML materializer accept optional geometry:
'rows-columns' (existing default) or 'cells'. Cells move/delete only original
coverage inside the band and do not fill the inserted gap; full-axis coverage
is clipped to the valid grid without adding newly inserted blank cells.
applyCellShift now derives source-only CF plans on every rule sheet before
any package mutation, then overlays the exact planned CF XML after ordinary
cell/formula/notes shifts. The source linked/dxf/extension materialization and
semantic read-back identity check are shared with row/column operations.

Only CF base and x14 CF blocks whose source reader is complete are excluded
from the existing ranged-feature guard. For geometry=cells, incomplete CF
throws before a plan is registered; unlike the existing rows-columns legacy
fallback it cannot enter range-only handling. DV/filter/hyperlink/object/table/
shared-formula protections remain. A newly exercised x14 DV fixture exposed
that the old guard matched x14:sqref but omitted the standard xm:sqref; this
specific guard now checks both, so validated CF does not accidentally admit
an intersecting x14 data validation. Unknown CF types/attributes remain refused.

Evidence: twelve originally real RED cell-shift CF contracts progressed to
GREEN; source guard and mixed-axis semantic inverse cases extend the file to
fourteen. /tmp/cf-cell-shift-final-green.log covers these plus existing cell
shifts; /tmp/cf-cell-shift-final-engine-types.log and
/tmp/cf-cell-shift-final-frontend-types.log cover strict typechecks. The mixed
insert/delete test compares per-cell formula semantics, not equivalent
rectangle tilings or forced re-merging across independently persisted parents.
The browser collector/history/native-save acceptance belongs to frontend/root.
No fixed serializer changes, production build or dist/static updates made.

Sheet rename CF follow-up: local sheets-edit adds case-insensitive sheet/A1
reference handling and shared cfvo@val/xm:f rewriting while protecting quoted
literal strings and external workbook references. The linked reader now checks
both threshold halves for semantic consistency instead of trusting only the
base projection. This is a disclosed local adaptation, not a change to fixed
xlsx-cf.ts. See CONDITIONAL_FORMATTING_SOURCE.md and the sheet-edits investigation
for 10-RED to 15-GREEN evidence and 135 targeted passing tests plus strict types.

Referenced sheet-removal CF follow-up: worksheetReferencesSheet additionally
scans formula cfvo@val using formulaReferencesSheet; this closes dataBar,
colorScale and iconSet refusal bypasses without changing fixed-source deletion
semantics or serializer. Three original REDs become GREEN, 30 targeted
removal/sheet-ops tests pass, then expanded removal boundary coverage passes
17 cases. See /tmp/cf-sheet-removal-engine-green.log and
/tmp/cf-sheet-removal-threshold-final-green.log; strict engine/bridge types pass.
Surviving XML/style bytes stay identical for allowed literal/external/unrelated
formula thresholds. No build, dist/static update or commit is included here.

Chart namespace reference follow-up: sheets-edit.readChartFormulas uses the
explicit saxes 6 runtime dependency in xmlns mode, recognizing only actual
DrawingML chart URI formula nodes across default/alias/scoped bindings.
chartReferencesSheet reuses it and existing literal/external-aware formula
semantics. Malformed XML throws; valid empty charts return no formulas.
Fixed-source xlsx-sheets.ts only recognizes c:f, so this compatibility fix is
a disclosed local adaptation. Chart rendering projection remains unchanged.
Evidence: 32 targeted engine tests pass, one owned-drawing cascade TODO remains;
strict engine/bridge types pass; one bridge bundle and nine native Python chart
removal contracts pass. See /tmp/chart-namespace-final-engine-green.log,
/tmp/chart-namespace-final-types.log and /tmp/chart-namespace-native-python.log.
Owned drawing cascade remains an independent full parity gap; its source
relationship closure and surviving incoming-reference protection are documented
in NATIVE_XLSX_CHART_SHEET_REMOVAL_INVESTIGATION.md, not claimed implemented.

## 2026-11-10 chart rename and owned satellite removal

Chart rename now identifies chart formulas by namespace URI using Saxes and rewrites only changed formula bodies after complete XML validation. Default/aliased namespaces, text/CDATA/entities and foreign c:f preservation are verified. This is a disclosed local compatibility patch: fixed GenOffice f8c17004 still uses a c:f regular expression. Multiple sheet renames compose from the already rewritten chart part.

Sheet removal now follows the fixed source owned internal relationship closure and preserves shared targets/subtrees reached by surviving incoming relationships. Only genuinely dying charts are skipped by reference/rename checks; removed part Overrides are dropped while Defaults and untouched part bytes survive. Namespace, path, relationship identity and missing-part validation are stricter local adaptations. Unknown/pivot root ownership remains refused. Removed tables additionally retain source case-insensitive structured-reference token checks in surviving worksheet XML and defined names, excluding removed local scopes. This engine guard does not claim frontend table deletion atomicity. The earlier owned-drawing TODO is now executable; final native/browser evidence is recorded in the parity audit and dedicated investigations.

## 2026-11-10 pivot source sheet removal

The fixed gateway's pivotCacheDefinition worksheetSource@sheet removal guard is
now applied by sheet-ops before package mutation. Public pure helpers live in
pivot-cache-source.ts (also available through the existing wildcard subpath).
Case-insensitive decoded sheet attributes follow fixed f8c17004 source semantics;
Saxes namespace URI/scoped binding handling, strict URI support and complete XML
validation are disclosed local compatibility improvements over the source regex.
Real openpyxl pivot ZIPs reproduce three original failures and now pass, while
unrelated sheet deletion retains the cache/pivot XML. See
PIVOT_SOURCE_SHEET_REMOVAL.md for scope and the 32 targeted passing tests plus
strict engine typecheck evidence. No frontend or production build is included.


## 2026-11-10 hidden column geometry preservation

The local `structural.ts::shiftColumnDefinitions` follows fixed GenOffice
`f8c17004fb730df11f0f743164ffd8b4281bb38c` gateway
`packages/xlsx-gateway/src/gateway/xlsx-structure.ts::transformColDefinitions`
and `moveRange` (source SHA-256
`550d5f6bfa6e5a02ee6900ef601f62ebfee9e651e773bff183f6955bb3583561`).
Whole-column insertion/deletion now moves/clips complete `<col>` ranges,
preserving their attributes. Interior insertion expands the enclosing range;
insertion at its start moves it, and gaps do not invent definitions. Banded
cell shifts do not move whole-column definitions.

`geometry.ts::setColumnWidthsXml` now patches only width/customWidth/bestFit on
the requested columns after splitting ranges. Hidden, style, outline, collapsed
and opaque attributes survive. Visibility remains an independent outline edit,
so explicit unhide followed by resize stays unhidden. No geometry diff suppression
was added: a structurally aligned baseline naturally removes the phantom width
patch. Integer/bounds validation and overlap rejection are local safety
adaptations; ambiguous overlapping column definitions are refused rather than
merging unknown properties. Single/double quoted attributes and whitespace
around `=` are supported by these two column writers, a local compatibility
extension over the fixed source attribute reader. This does not claim general
OOXML parser coverage or change all reader quoting behavior.

Evidence: fixed-source direct bundle comparison passes 37 vectors (32
insert/delete ranges and 5 width edits); targeted engine geometry7 and
structural/cell-shift25 pass. Frontend `workbook-geometry-hidden.test.ts`
independently inspects actual ZIPs with openpyxl, covers real Univer
insert/Undo/Redo, width preservation, explicit unhide, range attributes, malformed
ranges, overlap refusal and single-quote/spaced-attribute XML. Evidence logs:
`/tmp/geometry-hidden-source-parity.log`, `/tmp/geometry-hidden-quotes-green.log`.
Updated built smoke requires the shifted source hidden column D to survive
saving and rejects its former phantom width operation; new built execution is
owned by root after the next unified build, not claimed by these narrow tests.


2026-11-12 chart value-axis projection: `packages/xlsx-engine/src/chart-read.ts`
now retains the plot-linked `c:valAx/c:majorUnit` (positive finite number) and
XML-decoded `c:numFmt/@formatCode`, alongside the existing min/max/orientation.
This is a local bounded reader adaptation, not a writer replacement or a claim
of full chart axis support. The frontend uses the pinned chart-visual.ts scale
and its existing Univer number formatter; see the editor's
NATIVE_XLSX_VALUE_AXIS_CANVAS_ACCEPTANCE.md for source-oracle and final-pixel
proof, intentional all-negative zero-top correction and unsupported properties.


2026-11-12 category chart projection: the local chart reader retains bounded,
indexed single-level strCache/numCache/strLit/numLit labels and the numeric
category format, plus maxMin from the actual linked category axis. Sparse
indices remain null slots; duplicate/out-of-range points, excessive counts and
multi-level blocks return an explicitly empty projection rather than silently
reindexing or inventing labels. No source chart/cache bytes are rewritten.
See NATIVE_XLSX_CATEGORY_AXIS_CANVAS_ACCEPTANCE.md for the native adapter scope.


2026-11-12 explicit data-label projection: chart-read.ts retains plot/series
showVal/delete, canonical ctr/inEnd/outEnd positions, decoded label formats,
indexed point overrides and non-General value-cache formats. Plot settings are
bounded outside actual series blocks. Unsupported nonvalue flags, point text
or manualLayout, unknown positions, duplicate point identities and malformed
switches are marked unsupported rather than becoming raw value labels. This
local read-only adapter does not rewrite source label/cache bytes or implement
all label styles/layouts; see NATIVE_XLSX_DATA_LABEL_CANVAS_ACCEPTANCE.md.


2026-11-12 label-font preservation: the local reader projects explicit txPr
size (hundredths of pt), plain srgbClr and b, retaining missing-vs-false for
property inheritance. The native chart writer's mode/detail setters now use
SaxesParser direct-child byte spans instead of rebuilding all dLbls or matching
a nested point's numFmt/dLblPos. Existing root font XML, point overrides and
unknown children survive global edits; removing mode=none retains its existing
explicit plot-block removal behavior. Tests preserve raw point formats with >,
custom Unicode text and extension bytes. This fixes a local/shared legacy writer
limitation rather than claiming an unmodified upstream port. Full chart XML
prefix/schema normalization and complete label typography remain outside scope.

2026-11-12 chart label theme projection: chart-label-theme.ts follows the unique
internal workbook theme relationship and validates the actual complete palette.
parseThemePalette has an opt-in strict mode without default slot substitution;
existing cell callers keep their former behavior. chart-read resolves plain
schemeClr at plot/series/point label levels through existing style-color helpers.
Transforms and unresolved/ambiguous sources remain unsupported. Chart edits and
theme replay preserve original scheme tokens; no color math or writer added.
See report_editor/NATIVE_XLSX_DATA_LABEL_THEME_ACCEPTANCE.md for actual UI,
downloaded OOXML and independent pixel evidence and remaining limitations.

2026-11-12 chart label luminance: chart-label-color.ts uses existing SaxesParser
and style-color HLS conversion for bounded lumMod then lumOff on explicit RGB
or resolved scheme labels. DrawingML rounds color bytes like the fixed source;
cell tint keeps its old truncation. Unknown/repeated/nested/reordered or mixed
transforms stay unsupported. The original chart modifier bytes survive edits
and theme replay. Fixed source code execution matched 1120 cases; independent
Python rounding differences and a source comment discrepancy are retained.
See report_editor/NATIVE_XLSX_DATA_LABEL_LUMINANCE_ACCEPTANCE.md for evidence.
