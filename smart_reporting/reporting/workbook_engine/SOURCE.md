# Workbook engine source

Vendored from local sheets-web/packages/xlsx-engine, package @sheets-web/xlsx-engine 0.1.0, on 2026-11-03. The supplied sheets-web checkout has no committed HEAD; SOURCE-SHA256.json pins the exact source snapshot. Upstream provenance (genoffice f5247d3 and later local extensions) is preserved in UPSTREAM.md. License: Apache-2.0, as declared by sheets-web and its package manifests.

Only this engine and its tests are migrated. Node bridge and report integration are smart_reporting additions. Browser and server import this same package. No runtime dependency on adjacent sheets-web sources.

## 2026-11-05 selective upstream maintenance

Reviewed GenOffice `4b55db9ed1994575a695160ffc6cfd0bfc866211` (2026-11-04 snapshot). The engine remains the sheets-web browser-safe subset, with three upstream fixes backported: Excel 1900 serial-date grouping (`92ab9c46`), numeric text in baked pivot aggregates/calculated fields (`17cd6e4a`), and deterministic non-finite sort keys (`69880bc8`). See UPSTREAM.md for scope and exclusions. This is not a replacement with the complete latest `@genoffice/xlsx-gateway`.

SOURCE-SHA256.json retains the original migrated sheets-web snapshot. LOCAL-ADAPTATIONS-SHA256.json records the adapted package manifest. UPSTREAM-PATCHES-SHA256.json pins the files changed or added by selective upstream maintenance and the local native notes/filter integration described below. Apply the manifests in that order; later entries take precedence. Together they cover every file under packages/xlsx-engine (84 files), not the local bridge, root toolchain, documentation, LICENSE/NOTICE, or the hash manifests themselves. The exclusions are not upstream source claims. The manifests do not imply that unported upstream features are present.

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
