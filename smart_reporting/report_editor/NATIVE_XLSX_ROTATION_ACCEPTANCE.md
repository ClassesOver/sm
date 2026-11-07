# Native XLSX text rotation: source mapping, persistence and acceptance

2026-11-06. This closes one bounded Excel Home alignment slice, not Task 3 or
whole ExcelShell parity. Editing feature flags remain off. No deployment,
merge, source signing or publication changes are part of this slice.

## Original sources and implementation

The fixed GenOffice `apps/sheets/src/renderer/ribbon-actions.ts` at
`f8c17004fb730df11f0f743164ffd8b4281bb38c`, blob
`c38df65e12b3f2f22edd1d43583277516c34ae45`, dispatches `rotate:*` through
`sheet.command.set-text-rotation`: numeric counterclockwise-positive degrees,
or `'v'` for stacked text. This browser adapter reuses the installed Univer
**0.25.1** registered command through its public `syncExecuteCommand` facade.
It does not import the desktop dispatcher or invent a second rotation engine.
The installed command maps numeric values to `tr:{a:value}` and `'v'` to
`tr:{a:0,v:1}`; its existing command/mutation history supplies Undo/Redo.

Connected source controls: `rotate:45`, `rotate:-45`, `rotate:vertical`,
`rotate:90`, `rotate:-90`, `rotate:0`. Source OOXML 0–90 maps to the same signed
angle; 91–180 maps to `90-value`; 255 maps to stacked text. Reverse mapping
restores the exact OOXML unit. Imported nonpreset angles such as 37/127 remain
representable and do not acquire a false pressed preset. Invalid numbers are
not converted into valid angles. Clearing a nonzero source emits explicit
`textRotation:0`; absent/normal rotation does not create a phantom style delta.

The existing `LogicalStyle`/Univer importer/readback diff now carries rotation,
so an unchanged imported rotated cell remains unchanged during unrelated edits.
Only the existing `applyCellEdits` style field is submitted. Formula/value,
other font/alignment fields, merge ranges and defined names are not replaced
by a rotation command. Native draft restore rebuilds the workbook through the
same production engine and imports the resulting style. Source control state
is refreshed in place on selection and mutations, including restored state,
mixed/no-selection and loading/saving/closed states. Per-cell composed Univer
styles are used for selection state; a mixed or very large selection has no
pressed preset. The click target is not recreated during state refresh.

## Original reader defect and safe source boundary

A real XLSX roundtrip probe initially failed before the UI was enabled. The
writer emitted `<alignment textRotation="135"/>`, but the existing
`parseAlignment` reader called `numberAttribute(element, 'textRotation',
undefined)`. That helper always returned undefined for this calling convention
and searched for an imaginary child element. Its direct-attribute branch is
now corrected. The same pre-existing bug affected `indent`, which is also read
correctly after the fix; the native indent buttons remain disabled because
this slice does not implement their grid/writeback adapter. Font-size child
attribute reading is covered by the same regression and remains intact.

A second inspection found that the current workbook model does not import full
row/column and named/default-XF style inheritance. Enabling a Clear Rotation
button for those sources could claim an effective clear without writing one.
This slice therefore exposes `rotationReadOnlyReason` and **disables only these
new rotation commands** for sheets with row/column style references, a rotated
default/named XF, or a rotated XF explicitly disabling its alignment. The handler
also checks this source gate before dispatch, so stale/programmatic clicks
cannot bypass the UI state. A reason explains the limitation. This is a
conservative source boundary, not a claim that inheritance was implemented.

Original source SHA manifests remain unchanged. The workbook engine
`UPSTREAM-PATCHES-SHA256.json` records the two local reader adaptations and their
new regression; the browser vendor `LOCAL-ADAPTATIONS-SHA256.json` records the
style-map adaptation. `workbook-vendor/SOURCE.md` records its source callback
provenance. No dependency version or shared `native_office.py` change is needed.

## Actual checks and limits

- Frontend initial selection: 38 passed, one real-XLSX import/readback failure.
  After correcting the reader, that same roundtrip passed; an additional inherited
  source-state case passed. This represents **14 distinct new rotation cases**
  plus **26 existing Ribbon/native draft/recovery cases**, not a sum of repeats.
- Reader/source-gate regression: **13 distinct passing checks**, including all
  six wire rotations, absent/invalid/explicit-zero attributes, unaffected font
  size, row/column/default/named inheritance and explicitly disabled secondary
  alignment. The secondary-XF case prevents a naive regex from confusing a
  preceding self-closing XF with the actual target. Existing XML extraction
  helpers are reused for that check.
- Frontend TypeScript and strict engine-package TypeScript checks passed.
  Production bridge bundling/packaging, JavaScript syntax and scoped diff checks
  passed. The parent runs final merged production build/budget after all format
  workers stabilize. No complete repository/frontend/engine test suite was run.
- Real **Chromium 154.0.8037.57** on port 4194 clicked all six controls, starting
  from a clockwise source angle; checked active states after each conversion,
  Undo/Redo, actual page reload/native draft restore, save, downloaded-byte SHA,
  independent openpyxl readback and revision-2 browser reopen. Source context
  now uses the **actual** original SHA rather than the older fake smoke digest.
- The accepted save contains exactly one `applyCellEdits` style-only change:
  `textRotation:0` on A1. openpyxl independently confirms A1 normal rotation,
  existing center alignment/wrap/indent=2/bold/italic/14pt unchanged, B1 formula
  `=1+1`, B1 90-degree rotation/number format unchanged, C1 stacked rotation 255,
  the Revenue defined name and D1:E2 merge unchanged.

Final source SHA:
`b5417b5bcda483de47aab2a4b54dfacc551ef35ee8fc345467d4a20d0b099bee`.
Final downloaded SHA:
`4aab126d13e4ef7ac93128ca4f6c4bbb152579755874f292893b08a048781738`.
Production-packed `dist/cli.mjs` SHA:
`ef2022d997b003841573247e71a9adae11951a6320da3173e980302f5074885f`.

Browser receipt/files: `/tmp/pr190-xlsx-rotation-final-evidence`.
Run logs: `/tmp/pr190-xlsx-rotation-browser-final.log`,
`/tmp/pr190-xlsx-rotation-tests.log`,
`/tmp/pr190-xlsx-rotation-roundtrip.log`,
`/tmp/pr190-xlsx-rotation-inherited-ui.log`,
`/tmp/pr190-xlsx-rotation-reader-final.log`,
`/tmp/pr190-xlsx-rotation-reader-secondary.log`,
`/tmp/pr190-xlsx-rotation-types-accepted.log`,
`/tmp/pr190-xlsx-rotation-engine-types-final.log`.

Reproduce from `report_editor/frontend` after production-packing the current
workbook bridge:

```sh
WORKBOOK_SMOKE_CASE=rotation WORKBOOK_SMOKE_PORT=4194 \
WORKBOOK_SMOKE_EVIDENCE_DIR=/tmp/xlsx-rotation-new-evidence \
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
AGENT_REPORTING_WORKBOOK_ENGINE_DIR=/tmp/pr190-xlsx-rotation-final-runtime \
node smoke/workbook-native-save-smoke.mjs
```

Browser routes substitute authorization and revision registration. The original
bytes, backend transformer, downloaded XLSX and openpyxl consumer are real.
This is not a deployed-server, PostgreSQL/grant persistence, complete image,
Microsoft Excel desktop or broad rendering-compatibility certificate. The
browser's validator fixture reports success; no new nonblocking validation-fault
claim is made from it. The existing publication contract is unchanged.
