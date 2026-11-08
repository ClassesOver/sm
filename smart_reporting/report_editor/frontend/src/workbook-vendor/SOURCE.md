Migrated from sheets-web/apps/web/src, package version 0.1.0, on 2026-11-03. The supplied checkout has no committed HEAD; SOURCE-SHA256.json pins every migrated TypeScript source file. Original upstream engine provenance is recorded in reporting/workbook_engine/UPSTREAM.md. Apache-2.0; LICENSE and NOTICE included. Reuses original grid load/readback, value/style diff and geometry helpers. Runtime code has no dependency on the source checkout.

2026-11-05 review target: GenOffice `4b55db9ed1994575a695160ffc6cfd0bfc866211`. `create-univer.ts` retains the upstream plugin deduplication/registration semantics with local type adaptation; upstream has no later change to that helper. The data/style/session helpers are sheets-web extracts or rewrites, not a full copy of the latest desktop `univer-sync.ts`. Desktop formula-cache orchestration relies on state, recalculation and journal modules absent here, so it was not copied into the browser adapter. The shared local engine received three explicitly documented upstream fixes (see reporting/workbook_engine/UPSTREAM.md). These browser TypeScript files are unchanged by this maintenance; this review does not claim full desktop renderer parity or upgrade Univer dependencies.

SOURCE-SHA256.json preserves the original eight-file TypeScript snapshot. LOCAL-ADAPTATIONS-SHA256.json overrides its session-core.ts hash to record an existing local adaptation: the current file equals git HEAD and already differed from the source snapshot before this maintenance. Applied in that order, these manifests cover all eight TypeScript files in core/ and grid/. They do not hash LICENSE/NOTICE, this documentation, or the hash manifests themselves.

Latest review: `f8c17004fb730df11f0f743164ffd8b4281bb38c` (2026-11-05). The additional six upstream commits add desktop external-link break/retarget, formula-settle export and printing features; those depend on desktop/Rust gateway modules absent from this browser-safe subset. They are not claimed as integrated. Existing three backports remain unchanged.

The native workbook editor also uses the official Apache-2.0 Univer presets `@univerjs/preset-sheets-find-replace`, `@univerjs/preset-sheets-drawing`, and `@univerjs/preset-sheets-table`, all pinned to 0.25.1. They remain installed in the frontend dependency graph and are not copied or modified in this vendor directory.

`grid/decimal-step.ts` adapts GenOffice `apps/sheets/src/renderer/decimal-step.ts` at `f8c17004fb730df11f0f743164ffd8b4281bb38c`. `ui/ribbon-icons.tsx` is copied byte-for-byte from the same revision's `apps/sheets/src/renderer/ribbon-icons.tsx`. Only the icon module is included from the Ribbon dependency closure; the desktop `ExcelShell.tsx`, React shell state, file dialogs, renderer App, IPC, Electron filesystem access, and command dispatcher are excluded. The native ribbon maps its existing operation IDs to these browser-safe upstream glyphs and keeps its own narrow DOM host. See SOURCE-SHA256.json for the pinned sources and hashes.


2026-11-06 native rotation adapter: `core/style-map.ts` now imports and reads
OOXML textRotation through Univer's signed-angle/stacked `tr` shape, retains
explicit clearing in style deltas and leaves invalid angles unset. The original
SOURCE-SHA256 remains unchanged; LOCAL-ADAPTATIONS-SHA256 records this adapter.
The six native command values reuse fixed GenOffice `ribbon-actions.ts` at
`f8c17004fb730df11f0f743164ffd8b4281bb38c`, blob
`c38df65e12b3f2f22edd1d43583277516c34ae45`: signed numeric degrees or `'v'`,
dispatched to registered `sheet.command.set-text-rotation`. Only the browser-safe
callback contract is adapted; no desktop dispatcher is imported. Source files
with unsupported row/column/default/named-XF rotation inheritance are gated
readonly for these commands rather than advertising a clear operation that
cannot be represented by the current source model.

2026-11-06 native Find/Replace adapter: `grid/sync.ts` uses the public
`FUniver.executeCommand` for the pinned preset's find/replace operations and
exposes its existing snapshot projection for replacement budget preflight.
The search/replacement algorithm remains in the official Univer 0.25.1 preset;
no desktop command service or parallel replacement engine is imported.
SOURCE-SHA256 remains unchanged; LOCAL-ADAPTATIONS-SHA256 records this adapter.

2026-11-06 native custom number-format adapter: `core/style-map.ts` preserves
an explicit Univer `n.pattern: 'General'` through readback so resetting a custom
number format produces a format-only XLSX edit. Missing number formats remain
inherited/unchanged. The ribbon validates codes with the existing pinned
`numfmt` 3.2.6 parser; no format parser or full format dialog is vendored.
LOCAL-ADAPTATIONS-SHA256 updates only the style-map entry for this correction.

2026-11-06 strike/double-underline adapter: `core/style-map.ts` compares border
objects by value in style deltas, so an untouched border no longer produces a
pseudo-diff when a sibling font field (strike, double underline) changes.
Without this, a strike-only toggle emitted a spurious border edit. The ribbon
applies strike and single/double underline as style-only `FRange.setValue`
patches (one official undo entry each); clearing underline writes `ul` only and
leaves strike intact, instead of `setFontLine('none')` which clears both.
LOCAL-ADAPTATIONS-SHA256 updates the style-map entry for this correction.

2026-11-06 cell type marker adapter: `core/univer-data.ts` sets the Univer
`CellValueType` marker (`t`) on projected value cells. Without it, grid
features that branch on the type marker misbehave: the official
`sheet.command.sort-range` compared numbers as strings (lexicographic order),
so an ascending sort of a numeric column silently produced an identity
reorder. The readback only consumes `v/f/s`, so the marker cannot create save
diffs. Verified by a real-preset-stack regression (`workbook-sort-realstack`
test: sort now moves 1234.567/28.125 correctly and the reorder order is
non-identity). LOCAL-ADAPTATIONS-SHA256 adds the univer-data entry.

2026-11-08 geometry snapshot keys: `core/univer-data.ts` and `grid/sync.ts`
now project and read row/column geometry with Univer 0.25.1's real
IRowData/IColumnData keys — `h`/`w` in pixels and `hd` (BooleanNumber, 1 =
hidden) — as GenOffice `f8c17004` `apps/sheets/src/renderer/univer-sync.ts`
does. The migrated sheets-web snapshot used `height`/`width`/`hidden`, which
Univer ignores: file widths, heights and hidden rows/columns were not shown and
grid resizes/hides never reached the save-side geometry diff. Pixel
conversions are unchanged (`columnWidthToPixels`, `rowHeightToPixels`), so an
untouched load still diffs nothing. `isHiddenAxisEntry` is shared with the
filter visibility snapshot and the print source. LOCAL-ADAPTATIONS-SHA256
records both files; SOURCE-SHA256 is unchanged.
