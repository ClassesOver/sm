# Conditional-formatting snapshot adapter provenance

Sheet removal follow-up: worksheetReferencesSheet now scans formula cfvo@val
through the same formulaReferencesSheet API as ordinary and xm:f formulas.
This retains fixed-source referenced-removal refusal rather than inventing
#REF migration. dataBar/colorScale/iconSet threshold references now refuse
before any ZIP mutation. Case-insensitive and quoted references refuse; string,
unrelated-sheet and external-workbook thresholds still allow deletion while
preserving surviving worksheet/style bytes. Evidence: original three REDs,
then 30 passing removal/sheet-ops contracts, and expanded 17 passing removal
contracts; logs /tmp/cf-sheet-removal-engine-green.log and
/tmp/cf-sheet-removal-threshold-final-green.log. Strict engine/bridge types
passed. Browser atomic refusal and save acceptance are separate frontend work.

Sheet rename follow-up: local sheets-edit.renameSheetInFormula now uses a
case-insensitive matcher for A1 references and qualifiers, preserves literal
strings and external-workbook references, and rewrites cfvo formula attributes
through the same API as ordinary formulas and xm:f. Fixed source serializer
remains unchanged. The linked reader independently verifies paired threshold
counts/types/numeric values/formulas; stale x14/base halves no longer project
with issues=[]. It accepts existing min/max versus autoMin/autoMax compatibility
and normalizes only reference/function case and equivalent sheet quoting,
preserving formula string values and intersection spaces. Evidence: expanded
10-RED/5-GREEN, then 15-GREEN rename contracts, and 135-GREEN targeted rename,
snapshot and sheet-ops tests in /tmp/cf-sheet-edits-final-green.log; strict engine
and bridge typechecks in /tmp/cf-sheet-edits-engine-types.log. Frontend rename
transactions and actual native save/reopen acceptance are separate evidence.

Fixed source GenOffice commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

`packages/xlsx-engine/src/conditional-formatting-source.ts` is a byte-identical copy of `packages/xlsx-gateway/src/gateway/xlsx-cf.ts` from that commit; both SHA256: `db38a4ca48933595db8019acce5f45b27f1fdff2f01d43bd6ae7abd84b16e18e`. Apache-2.0, repository LICENSE/NOTICE retained. It has no import dependencies. No modification of the original source serializer is concealed as upstream behavior.

`conditional-formatting-read.ts` is a local browser adaptation of the fields read by `apps/sheets/native/xlsx-engine/src/worksheet.rs` (`ConditionalRule` and CF parsing), and `apps/sheets/src/renderer/univer-sync.ts:7301 buildConditionalRule`. Rust cannot be imported into this TS engine; the adapter maps base OOXML rules to the source serializer's native Univer wire structure. The source serializer verifies each projected rule's attributes and formulas on read-back; local checks additionally cover complete ranges, duplicate/invalid priorities, dxf references, unknown fields and extension-bearing data. Explicit schema defaults and conventional solid foreground fill representation are normalized without erasing unknown fields.

`conditional-formatting-snapshot.ts` is local package plumbing: resolve target sheets via the existing workbook relationship resolver, inspect source identity, apply the fixed-source full-set serializer, intern dxfs with existing StylesheetEditor, inspect the resulting projection, and assemble only touched ZIP entries. Existing `rules.ts::applyCfRules` keeps its append contract.

Current incomplete source cases are explicitly rejected only for the CF replacement edit; unknown CF XML remains in original bytes. This is a protection against loss, not a claim that all source CF editing is complete. Broader equivalent external XML, renderer hookup, NativeDraft/protocol wiring and final GUI remain separate required work. No report publication or artifact download path is modified.

The next adaptation implements the fixed source's linked-x14 strategy: a unique base x14:id must match one extension rule with the same range/type/priority and standard x14/xm namespace identities. Its base block and sheet extension remain byte-identical while ordinary rules are replaced. Removal or modification of the preserved rule is refused. A local semantic full-wire identity check additionally prevents silent loss of edits to x14-only visual fields that the base serializer itself does not inspect. The original negative fill and gradient are projected for rendering; they remain immutable on this preservation path. The reader exposes linkedRuleIds and linkedRules for the future editor guard.

For packages without styles.xml, the adapter follows existing rules.ts plumbing: read the engine's blank stylesheet template, but add a stylesheet/content-type/relationship only when an interned dxf actually requires one. Pure dataBar edits do not create unused stylesheet parts. Existing foreign styles relationship targets are not implicitly retargeted. Both initial missing-styles and linked-roundtrip scenarios were captured as real ZIP RED cases before implementation.

The public workbook reader now follows fixed Rust visuals/styles.rs read_styles
when the optional stylesheet is absent: one empty default style, no invented
font, size or color, and no package writes. Missing dxf references remain
incomplete identities. Fixed Rust visuals/colors.rs resolve_color and fixed TS
xlsx-style-read.ts discard any ARGB alpha byte; the local complete reader now
does the same for valid colors, including openpyxl's default 00 alpha prefix.
Lexical identity normalization is confined to valid color rgb attributes;
unrelated fields and malformed hex are still checked, not discarded.

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
