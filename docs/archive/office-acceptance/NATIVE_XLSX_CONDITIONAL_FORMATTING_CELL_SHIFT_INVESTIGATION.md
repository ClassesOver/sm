# CF Insert/Delete Cells: next-stage investigation

Status: real RED evidence only; production, bridge dist and frontend static bundles remain frozen. This is separate from the completed row/column CF partition stage.

Fixed GenOffice source: `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

## Source provenance and actual behavior

- `apps/sheets/src/renderer/insert-delete-cells.ts:28-33,116-125` dispatches native `insert-range-move-right/down`, `delete-range-move-left/up`. Its tests cover dispatch/selection choices, not CF persistence. File SHA256 `dc071fda910bcd97847774846650b88d50e426ceb66c625942015b3f86310ac4`.
- Source `univer-sync.ts:6385 collectCfStates` collects the full native CF rules of each `editJournal.cfDirty` sheet into the gateway payload. Therefore the local cell-shift module's old opening comment about upstream full-model serialization is an incomplete historical description; the actual CF save path has explicit CF snapshot collection. Source SHA256 `677f67710889e5d17e5e643177090757cd89534997589930976e78dd4e8cbf4e`.
- Installed official `@univerjs/sheets/lib/es/index.js:7462 handleInsertRangeMoveDownCommon` and `:7500 handleInsertRangeMoveRightCommon` split original coverage into unaffected rectangles plus affected original cells translated by the inserted width/height. They use `Range.foreach`/ObjectMatrix, so their per-cell implementation must not be copied for whole-column workloads.
- This scope rule differs from whole-row insertion: B1:B4 with insertion of cell B2/down becomes B1 plus B3:B5, leaving B2 unpainted. Similarly A2:D2 with B2/right becomes A2 plus C2:E2. The existing shared planner intentionally grows an interior whole-row range; that branch currently applies to band specs too. Simply removing the cell-shift guard would therefore paint the inserted gap incorrectly.
- Official CF UI `ConditionalFormattingFormulaRefRangeController` registers both own coverage and relative formula dependencies, and uses Set/Add/Delete followers. Add still unshifts descendants above unrelated higher-priority stop rules. This is independently confirmed by the browser probe below.

## Local production boundaries

`packages/xlsx-engine/src/cell-shift.ts:42 cellShiftSpec` already converts right/left/down/up into `ShiftSpec.band`. `assertRangedFeaturesClear` rejects a base CF scope intersecting the affected band, before any package mutation. This is a refusal, not supported CF cell shifting.

`applyCellShift` shifts ordinary worksheet formulas/qualified references, but never calls the shared CF planner/XML materializer. Therefore an Other-sheet CF that depends on Source cells in the band is allowed through yet retains its original unsplit dependency formula. The missing dependency migration is separate from the explicit own-sheet scope guard.

Frontend currently records the official cell-shift command, then runs `currentOperations()` and undoes unsupported intersecting-source features after the command. The row/column trusted CF collector only recognizes line commands, so official cell-shift CF followers are not normalized into the shared parent-priority transaction. A cell shift with only Other-sheet dependencies can remain accepted while its split sibling overtakes a higher stop rule.

## Reproducible real RED evidence

Engine: `packages/xlsx-engine/tests/conditional-formatting-cell-shift-gap.test.ts`.

Run from workbook_engine:

```sh
./node_modules/.bin/vitest run packages/xlsx-engine/tests/conditional-formatting-cell-shift-gap.test.ts
```

`/tmp/cf-cell-shift-engine-red.log`: five real failures. Own down/right CF is refused; cross-sheet insertion/deletion dependencies are unchanged rather than partitioned; directly calling the current band planner fills the inserted coverage gap. These are intentionally active gap tests, not expected-failure assertions or skipped acceptance.

Browser: `frontend/smoke/workbook-cf-cell-shift-gap-probe.mjs`.

Run from frontend:

```sh
node smoke/workbook-cf-cell-shift-gap-probe.mjs
```

`/tmp/cf-cell-shift-browser-red.log`: Source A2/down command returns true. Other original green relative rule is partitioned into B1/Source!A1 and B2:B4/Source!A3 by official code, but the B2:B4 descendant is placed above the existing TRUE red stopIfTrue rule. `pageErrors=[]`. This shows dependency registration works without a workbook-prefix workaround. This cell-shift official result keeps correct Other coverage, unlike the previously observed whole-row official B5 expansion.

## Minimal shared implementation plan

1. Give the shared planner an explicit geometry mode (`rows-columns` versus `cells`), defaulting to the current row/column contract. For cells, preserve no-move coverage, translate only coverage within the band, omit deleted cells and do not grow the preceding piece over the new gap. Disable full-axis inserted-cell coverage filling in cell mode. Formula dependency partitioning, sorted anchors, mixed axes, offset/shift transforms, priority slots and rectangle budgets stay shared. Add four direction contracts, partial-band ranges, full deletion, whole-column/whole-row boundedness and quoted/mixed dependencies.
2. Route `applyCellShift` through the shared XML materializer on every source rule sheet, using original trusted CF XML before cell geometry writes and the same band spec/mode. Preserve raw dxf, source-derived linked twins/IDs and extension visual fields. Final read-back must exactly equal the plan. Lift only the validated CF portion of `assertRangedFeaturesClear`; keep existing table, DV, filter, hyperlink, object, shared/array and invalid/ambiguous-source boundaries. Do not broadly ignore `extLst` or `sqref` to bypass other guards.
3. Extend the frontend trusted structural collector to these four native cell-shift commands, derive its spec through the existing `cellShiftSpec`, and reuse the same full-sheet ordered mutation transaction as row/column CF. Remove only actual official CF follower objects from that command result, plan all rule sheets/dependencies first, validate rules/budget, and generate one undo/redo item. Keep arbitrary direct linked edits guarded. Avoid relying on asynchronous undo as successful support.
4. Upgrade the browser probe to own-CF scope plus cross-sheet dependencies, then undo/redo, draft reload, Python native save and revision reopen. Verify inserted gaps stay unpainted, parent-priority order survives, Other host cells remain unmoved, linked base/twin scopes and IDs match, unrelated package entries stay byte-identical, and no phantom CF snapshot appears after save. A rejection or remaining one-group dependency does not satisfy these contracts.

No implementation or broad test run was performed in this investigation stage.

## Engine implementation update

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

## Frontend collector and real save acceptance

The wrapper forwards the same explicit cells geometry to the shared planner. The collector recognizes all four native commands, plans every rule sheet before replacing official CF followers, retains non-CF DV/table mutations and preserves parent priority slots. DV save/budget preflight runs before any result-array mutation or ownership registration. Four-direction coverage/undo contracts plus existing row/column contracts passed: `/tmp/workbook-cf-cell-shift-frontend-red.log` captures six real failures before implementation; `/tmp/workbook-cf-cell-shift-frontend-green1.log` passes 15 targeted cases.

Real native undo exposed a separate ordering contract: all four installed official cell commands reverse the entire undo array before registering history, unlike the line commands. The collector now reverses only its own complete CF transaction in cell mode; official DV/table followers retain their existing order. `/tmp/workbook-cf-cell-shift-dev-undo-order-red.log` records both sheets becoming empty on undo; four command-specific reverse-history tests capture the same RED in `/tmp/workbook-cf-cell-shift-undo-order-red.log` and pass in `/tmp/workbook-cf-cell-shift-undo-order-green.log`.

Real saving then exposed CF display styles being copied into newly inserted blank cells by official `getCell(...).s`. Diagnostic `/tmp/workbook-cf-cell-shift-style-diagnostic.log` proves original A2 raw `{v:2,t:2}` has no style, projected getCell adds yellow CF fill, and official nested set-range-values copies it before the outer collector runs. `workbook-cell-shift-raw-style.ts` scopes an exact insert-down/right command to its synchronous construction phase, normalizes only the first matching style-only automatic batch to `getCellRaw(...).s`, and expires on completion/disposal or the next microtask. It preserves genuine direct styles, ordinary value edits, later user styles and foreign/mismatched commands. Native commands without params use the actual current selection. Source projection/real saved fill RED remains in `/tmp/workbook-cf-cell-shift-dev-extra-cell-style-red.log`; helper module RED and selection RED remain in `/tmp/workbook-cf-cell-shift-raw-style-red.log` and `/tmp/workbook-cf-cell-shift-raw-style-selection-red.log`. Nine helper plus nine collector tests pass in `/tmp/workbook-cf-cell-shift-raw-style-green2.log`; final frontend typecheck `/tmp/workbook-cf-cell-shift-raw-style-types.log` exits 0.

After root bridge bundle `/tmp/office-cf-cell-shift-engine-bundle.log` exits 0, `/tmp/workbook-cf-cell-shift-dev-stylefix-final.log` completes with exit 0: Source A2/down keeps own coverage `A1 A3:A5` with no raw or saved direct fill in A2; Other retains ordered TRUE/stopTrue B1:B4, Source!A1/B1, Source!A3/B2:B4 at priority 1/2/3. Native undo restores exact original rule ids/bodies, redo and real draft reload restore the plan, Python patch/openpyxl saving and revision 2 reopening pass. Only the two worksheet XML package entries change, Other values remain unmoved, and pageErrors=[].

The strict payload contains applyCellShift plus one verified actual native expansion height: before anchor/default 24px, after rowData[5].h=24px, saved applyRowHeights index5=18pt. It contains no CF snapshot or projected direct cell style. An earlier probe incorrectly expected 24 points; `/tmp/workbook-cf-cell-shift-dev-stylefix.log` preserves that units-only failure before correcting its px-to-point assertion. Real context/save/revision HTTP is supplied by the probe, with actual Python file mutation. Pure UI static probe `smoke/workbook-cf-cell-shift-built-smoke.mjs` (4220) is ready but awaits root's unified build; dev evidence is not a final static acceptance claim.

## Final pure UI static acceptance

Root unified build `/tmp/office-cells-cf-word-width-build.log` exits 0 in 39.81s; matching budget and budget-contract checks exit 0 without raising caps. `node smoke/workbook-cf-cell-shift-built-smoke.mjs` completes once with process exit 0, evidence `/tmp/workbook-cf-cell-shift-built-final.log`. No runtime injection or dev-module route is used. Real ribbon Insert Cells/down, native CF manager, File undo/redo, persisted draft reload, actual Python patch/openpyxl save and revision 2 reopening all pass.

Saved Source coverage is exactly `A1 A3:A5`, A2 direct fill is null, source values `[1,null,2,3,4,5]`; Other values remain `[1,2,3,4,5]`. Other CF is ordered TRUE/stopTrue B1:B4 priority 1, Source!A1/B1 priority 2, Source!A3/B2:B4 priority 3. Strict operations contain only applyCellShift Source A2/down and verified native expansion applyRowHeights Source index5=18pt; saved row6 height is 18pt. Only sheet1.xml and sheet2.xml change in the package.

All 333 actual JavaScript responses are HTTP 200 and match on-disk SHA256. Main `lazy-workbook-main-7CUbHnCf.js`, engine `lazy-workbook-engine-B-0ai3tJ.js`, collector `lazy-workbook-structure-followers-DlEsSu8J.js`; pageErrors=[]. The browser receives probe context/save/revision HTTP and invokes actual Python file processing; this is static browser plus real file persistence acceptance, not a production HTTP end-to-end claim. The actual browser fixture proves down insertion with own/cross-sheet CF; four directions are covered by directed wrapper/collector/engine contracts, not four independent static GUI fixtures.
