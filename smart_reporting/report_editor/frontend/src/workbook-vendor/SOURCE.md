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

2026-11-09 AutoFit Row Height: the loader marks file row heights explicit
(`ia: 0`, as `setRowHeightsForced` writes); `readBackSnapshot` reports rows the
grid sizes automatically (`ia: 1`) as `autoHeightRows`; `geometryChanges`
(`core/data-tools.ts`, now recorded in LOCAL-ADAPTATIONS-SHA256) emits
`heightPoints: null` for such rows only when the file had sized them, which the
engine writes as a height reset. `core/session-core.ts` carries the new
readback field.

2026-11-09 inline cell style readback: `grid/sync.ts` resolves a cell's `s`
either as a style id or as an inline style object. Univer's range moves
(Insert/Delete Cells shifts, drag-moves) store the moved cell's style inline,
so reading `s` only as an id dropped the moved formatting and the save diff
emitted a style reset (found by the real-browser Insert Cells acceptance).

2026-11-09 Boolean readback: `grid/sync.ts` restores typed Boolean cells stored by Univer as 1/0 before native diff/save. Numeric cells without the Boolean marker remain numeric. Covered by real command, undo/redo, draft restore and downloaded XLSX openpyxl readback.

2026-11-09: core/dedupe.ts is copied byte-for-byte from GenOffice apps/sheets/src/renderer/dedupe.ts at f8c17004fb730df11f0f743164ffd8b4281bb38c. Native adapter preserves the upstream whole-row, case-insensitive comparison and optional header contract, with one atomic command and existing draft/save budget checks.

2026-11-10 outline adapter: core/univer-data.ts projects imported row/column outlineLevel/collapsed into official axis custom metadata and sheet summary directions into worksheet custom metadata; native axis structural operations retain these values. The local workbook-outline module owns editing/save differences, not this vendor projection. LOCAL-ADAPTATIONS-SHA256 pins the updated file; the original SOURCE snapshot is preserved. Gutter overlays and keyboard outline shortcuts are not claimed by this adapter.

2026-11-10 cross-highlight host module (outside the vendor directory):
`../workbook-cross-highlight.ts` derives from GenOffice
`apps/sheets/src/renderer/cross-highlight.tsx` at
`f8c17004fb730df11f0f743164ffd8b4281bb38c`.
Upstream source SHA256:
`74390d8cfbda80486de266b1cca554139f61220de2bd58062b8aa8d1bf0cbe38`.
Adapted host module SHA256:
`115e9a92f5aa1e303d69025c960e4158188bb5835e7157ea8919698aabeb6541`.
These hashes document this separate host module and do not add a file to the
vendor SOURCE-SHA256 or LOCAL-ADAPTATIONS-SHA256 manifests. The host changes
the runtime type import and preference key; isolates rendering state with a
WeakMap keyed by the actual Worksheet; listens to Univer 0.25.1's official
`sheet.operation.set-selections` command because its facade has no
`Event.SelectionChanged`; and clears state on sheet replacement/disposal.
RTL row rectangles use the minimum/maximum of the two endpoint x coordinates:
the upstream subtraction produced a negative width when real skeleton columns
ran right to left, dropping the row band (confirmed by built canvas pixels).
The upstream segmented viewport approach, primary active-cell targeting,
canvas colors/layer, repaint service and printing exclusion remain intact.
Ribbon/main connect this reading preference without workbook operations or
NativeDraft writes.

2026-11-10 Go To reveal host module (outside the vendor directory):
`../workbook-goto-reveal.ts` adapts `revealCellBelowFreeze` from GenOffice
`apps/sheets/src/renderer/univer-sync.ts:917` at
`f8c17004fb730df11f0f743164ffd8b4281bb38c`.
Upstream whole-file SHA256:
`677f67710889e5d17e5e643177090757cd89534997589930976e78dd4e8cbf4e`.
Host helper SHA256:
`49b94e723cf395b5ea580d5069ad4514392a7366c877f8600187ad463bf0a35a`.
The original official facade scroll/visible-range correction and RTL settling
strategy remain. Host adaptation scopes generation/timers to each instance,
cancels on replacement/disposal/new navigation, checks all official frozen
viewport ranges before moving a visible target, and returns verified visibility
(or cancellation) for truthful main feedback. This host file is not part of the
vendor directory hash manifests. Main retains setActiveRange and does not load
the upstream application's separate lazy-workbook machinery.

2026-11-10 Host Page Break Preview integration (outside vendor manifests):
`workbook-page-break-preview.tsx` adapts the pinned GenOffice
`apps/sheets/src/renderer/page-break-preview.tsx` range-layer presentation,
source SHA256 `9f386d78691b4fda8b8b163d99273fc21095452f37a4432c937f638a31bf73f5`.
Pagination itself reuses the host `planSheetPrint` and actual save-operation
replay, rather than copying the source approximate page-size helper.
`workbook-page-break-controller.ts` handles actual Worksheet identity and
async/disposal lifecycle; `workbook-page-break-context.ts` rebases field
captures through the shared structural transformers. Source and acceptance
scope: `NATIVE_XLSX_PAGE_BREAK_PREVIEW_ACCEPTANCE.md`. Host file identities:
`workbook-page-break-preview.tsx`: `2f3ba3fde73d497f2c34cf989cac32bc23e8634ba68f391922734c5e308f2049`.
`workbook-page-break-controller.ts`: `45b1e18a132495186015a21802a0306eb3d8ddb1731a87f11e7305f03e13bca3`.
`workbook-page-break-context.ts`: `d65137f2357e943d0bd203ea5ce3a328a9f740cdcc5825bd7735ca45e50712ab`.

2026-11-10 native formula-trace host adapter: `../workbook-formula-trace.ts`
and `../workbook-formula-trace-controller.ts` adapt the fixed GenOffice revision
`f8c17004fb730df11f0f743164ffd8b4281bb38c`. Upstream source SHA-256:
`apps/sheets/src/renderer/trace-arrows.tsx` =
`eadb96ce844dd76c43b3c1c175d649a25c84ba08f4cd7ae738965dee19e7c673`;
`formula-closure.ts` =
`56382524c6ce217900a0f231d8eb7422b0f2bf97b7788b2394bae99f87883c21`;
`ribbon-actions.ts` =
`e4effd7feda2b4e9c6f8feb1b7f976b0b6325a80a2e690cb4fd17e46888efa11`.
The host uses formula-text direct references and official Univer float DOM ranges,
not a dependency-graph API. Local bounds, incomplete-reference warnings, lifecycle
cleanup and RTL single-cell float anchors are host adaptations. Entirely hidden
ranges and merged anchors/endpoints are refused with an explicit reason rather
than showing misleading arrows. Host modules are outside the vendor hash lists.

Follow-up built alignment correction: source range-SVG geometry cannot preserve
both endpoints when official freeze clipping applies different transforms to
its corners. Each arrow now connects the actual visible clipped DOM centers of
two official single-cell floats; the host only draws the line/arrowhead. Current
float ancestor styles trigger a bounded scheduled update, and ref rebinding and
disposal release observers. Offscreen endpoints hide their arrows with explicit
feedback; freeze-crossing highlights split along the official pane boundaries.

2026-11-10 native Watch Window host adapter: `../workbook-watch-window.ts` and
its CSS adapt GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:
`apps/sheets/src/renderer/WatchWindowPanel.tsx` SHA-256
`c05cf24faa4d7e3d14ba594bd370c6478597a77ca94c9b44e5322a681098cd52`;
`App.tsx` SHA-256
`d52ad546fef9d3856046c11311bf7570e35dc203d3f0db852eb1cfe5884b0b14`
(addWatchSelection/resolveWatch, watch toggle/mount);
`styles.css` SHA-256
`e0faabcde838f5ad9bd2af5deb51b48cda35142f9854068cba339a6e86bfb88f`.
The browser host preserves stable sheetId/coordinate keys, per-add 20-cell cap
(not a global cap), de-duplication, close/reopen list state and mounted-only
800ms updates. Display values/formulas come from the existing official Univer
facade. Local adaptations isolate workbook replacements, preserve keyed DOM
controls/focus, and mark out-of-bounds/unavailable reads as gone. Watch state
never enters XLSX, draft or history. These host files are outside vendor hashes.

2026-11-10 native Error Checking host adapter: `../workbook-error-checking.ts`
adapts the complete/current-sheet branch of GenOffice
`f8c17004fb730df11f0f743164ffd8b4281bb38c`,
`apps/sheets/src/renderer/ribbon-actions.ts` SHA-256
`e4effd7feda2b4e9c6f8feb1b7f976b0b6325a80a2e690cb4fd17e46888efa11`.
It scans the official current worksheet's sparse cell matrix for existing result
values, cycles to the next row-major error and uses official range activation
plus the existing host reveal controller. It does not evaluate formulas or
implement the streamed file/journal service. Local adaptations use exact Univer
`ERROR_TYPE_SET` plus upstream modern FIELD/CONNECT/BLOCKED/UNKNOWN literals,
avoiding upstream loaded-branch prefix matches and incomplete error taxonomy.
Current-sheet/current-result feedback, per-instance concurrency, workbook/sheet
identity checks and reset/disposal protect async navigation. Readonly, protected
and saved workbooks remain navigable; loading/saving/calculation locks disable
checking. No watch/error state, formula changes, history or draft operations are
written. The adapter is outside vendor hash lists.

2026-11-11 CSV selection import: `grid/csv-import.ts` extracts the browser-safe
decoder, delimiter parser and numeric recognition functions from GenOffice
`f8c17004fb730df11f0f743164ffd8b4281bb38c`,
`packages/xlsx-gateway/src/gateway/csv-import.ts` SHA-256
`b079c025774d89410ca8b861365c67c5b4525df0cfb7a2a4be87c3e0bae3f552`. XML/package writer imports and functions are omitted.
The local decoder evaluates preferred legacy character sets before BOM-less
UTF-16 guesses so equal-score short GB18030 CSV remains Chinese. The adapted
file SHA-256 is `7e6a2a2d39386648e963c07ef2321870dc6b27901d4729c7ac564f1fec935548`.
`../workbook-import-csv.ts` adapts selection import from
`apps/sheets/src/renderer/data-tools-actions.ts`; it adds stale-target/lock
guards, explicit string typing and old-formula clearing, and native write
readback verification. This host adapter is outside vendor hashes. See
`docs/parity/2026-11-11-workbook-csv-import.md` for evidence and limits.

2026-11-11 Queries & Connections: `grid/workbook-queries.ts` adapts the complete
read-only walker from GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`,
`packages/xlsx-gateway/src/gateway/xlsx-connections.ts`. Only helper imports change;
the local engine supplies XML attribute decoding and workbook sheet parsing.
`grid/query-parts.ts` extracts parseRelationships/tableDisplayName from
`xlsx-sheets.ts` and relsPathFor/resolveRelTarget from `xlsx-drawing-add.ts`.
The primary source files and adapted outputs are recorded in the SHA-256 lists;
the drawing helper source SHA-256 is afd5da76e6767c21a900abe91627cb02c487cf2901f616b95e890a4d50688016.
`../workbook-queries-reader.ts` adds safe ZIP part reading, SAX namespace/root
validation and comment/foreign-namespace removal, bounds checks and display-only
credential redaction. `../workbook-queries.ts` and its isolated CSS adapt
`apps/sheets/src/renderer/QueriesDialog.tsx`: real empty/error/loading states,
connection-only disabled entries, quoted destination navigation and modal focus.
The controller checks workbook identity, generation and loading/saving locks.
No query engine, external fetch, workbook mutation, draft or history writes are
introduced. Host adapters are outside vendor hashes.

Queries host adapter review corrections (2026-11-11): free-form connection
descriptions are omitted from the display projection; names sanitize UID and
URL userinfo. SAX canonicalization only emits actual OOXML metadata parent
paths, excluding nested extension payloads. Vendor source files are unchanged.
