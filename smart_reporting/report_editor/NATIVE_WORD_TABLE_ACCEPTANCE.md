# Native Word table structure: preservation adapter and bounded backend

2026-11-06. This implements the backend slice that follows
`NATIVE_WORD_TABLE_PLAN.md`; Ribbon structure commands are still unavailable.
The fixed GenOffice engine remains `f8c17004fb730df11f0f743164ffd8b4281bb38c`.
No vendor source was changed.

## Problem, original evidence and remedy

The original probe produced valid content matrices while losing `mirrorIndents`
and paragraph `rsidR` in every regenerated table (13 cases). Rebuilding modeled
paragraphs therefore could not establish preservation. The new native adapter
uses the pinned `generateTableModelXml` for structure, grid and empty new cells,
then restores surviving **whole source cells** by their original row/column.
Only the original `tcW` width attribute is changed when required. Original
paragraphs, runs, attributes, cell properties, surviving row properties and table
properties are retained; no match-by-text or client-supplied XML/model is used.
The existing `splitXmlChildren` is reused for scoped XML navigation.

`bridge/docx-table-structure.ts` owns the source gate and transformation.
`bridge/edit-docx.ts` validates anchors and batch rules, applies the operation,
then reopens the saved bytes and checks exact target XML, expected matrix and
column widths before writing an output file. A no-op engine cannot report a
successful structure edit. Python's existing wrapper admits the four kinds and
continues checking source/output identities.

## Wire and scope contract

Each operation has exactly:

```ts
{
  kind: 'insertTableRow' | 'deleteTableRow' | 'insertTableColumn' | 'deleteTableColumn',
  blockId: string,
  expectedObjectSha256: string, // source whole-table hash, not a cell hash
  index: number               // source coordinate; insertion gap [0,n], deletion [0,n)
}
```

Inspection exposes `structureEditable`, `structureReadOnlyReason`, `rowCount`
and `columnCount` separately from text/cell editability. The backend capability
is `simpleTableStructure`; this does not mean the Ribbon can dispatch it yet.

- Only top-level, rectangular, fixed-width tables with positive integer twip
  widths, matching tblW/tblGrid/tcW and a conservative property subset qualify.
  Explicit total width is preserved. Source table/row/cell shell attributes are
  rejected rather than silently dropped. Complete source paragraph XML survives.
- Merges, nested tables, grid gaps, floating/RTL tables, numbering, links,
  bookmarks, comments, fields, pictures, content controls and tracked changes
  are excluded. Unknown structural properties and XML comments/instructions
  are excluded. Detailed reason codes explain unavailable source objects.
- Source/result budgets: 100 rows, 30 columns, 1000 cells; table XML ≤1 MiB.
  Result budgets are checked before insertion. Deleting the last row/column is
  forbidden; a width less than two twips cannot be split.
- Inserting a column splits the adjacent width, including odd values, without
  changing total width. Deletion gives its width to the next surviving neighbor
  (the previous one at the end). Both width arrays are kept consistent.
- New cells are empty, without copying source content/paragraph metadata.
  New rows have no source height/cantSplit. Inserting **inside** an existing
  repeating-header prefix adds an empty header row so the prefix stays
  contiguous; insertion immediately after the prefix is a normal row.
  Noncontiguous source header flags are rejected.
- At most one structure operation per source table per batch; same-table text
  patches are rejected in either order. Different tables and body edits may
  share a batch. All requests validate against the same source snapshot.
- Saving changes the source SHA, therefore all table/cell IDs are reissued.
  Old table IDs/hashes and old cell IDs must fail against the saved file,
  including when combined with the fresh table ID. Fresh cell anchors remain
  usable. This phase does not invent a migration of old cell identities.

## Recorded verification

| Boundary | Actual observation |
| --- | --- |
| Independent preservation probe | `--preserve` ran original-save plus 12 first/middle/last operations: **13 passed, zero property-loss cases**. Whole paragraph canonical XML, cell properties except allowed width change, matrices, row properties, widths and non-target package files were independently checked by python-docx/lxml. Original save remained byte-identical. |
| Native backend | Initial **36 passed**; six additional duplicate-content/mixed-run/multiple-paragraph/odd-width/min-width/result-budget checks passed; the new silent-write fault test and literal-dollar XML regression passed. **44 distinct new checks**, not a sum of reruns. |
| Affected existing path | Five existing text/cell/complex-source/fault checks passed after updating the isolated fault fixture to include its newly imported adapter. No whole repository suite was run. |
| Actual HTTP flow | One DOCX ASGI upload/preview/save/download/SHA/idempotent retry/revision-reopen case passed. It combines column insertion and source paragraph metadata preservation with body, link, spacing and section edits. Validation failure still returns the actual generated-file download. |
| Packaged offline runtime | The same expanded DOCX HTTP case passed in **Node 22**, `--network none`, read-only container, production-packed bridge (**1 passed, 7.18s**). No bridge sources/node_modules are needed in the runtime package. Python dependencies/application are read-only host mounts: `mounted-runtime-probe`, not a complete application image. |
| Static checks | Strict TypeScript for bridge/adapter passed; production bridge bundling and packaging passed. Ruff passed for the new tests, Python probe/wrapper and affected HTTP file; diff checks passed. The legacy bridge test module was not asserted lint-clean. |

Probe source SHA:
`950b614601096d7d33ecbe56eaafa660af718e9fcf8de6944430915f8181db16`.
Packaged `dist/edit-docx.mjs` SHA:
`bf22bae04cd7543ca164394eb1949ba92cda3d91369acb6570f02891d973616f`.

Reproduce the independent probe from the repository root (new output directory):

```sh
.venv/bin/python scripts/probe_native_docx_tables.py /tmp/word-table-preserve-new --preserve
```

The probe without `--preserve` remains available to reproduce the original
serializer limitation; it does not claim that the vendor serializer was fixed.
The flag's original-save control plus 12 structural outputs include source,
engine/independent matrices, per-output hashes and exact property-loss lists.
`preservationAdapterVerified:true` is recorded, while `structureReady:false`
means the complete user-facing/desktop scope is not accepted.

New backend tests live in `reporting/tests/test_docx_table_structure.py`.
Targeted logs and evidence are retained under `/tmp/pr190-word-table-*`.
The first affected regression run found an isolated test fixture missing the new
module, not a file-write defect; after copying the adapter, its original silent
cell-write fault assertion passed. One subsequent regression selection was too
broad and was interrupted (25 passed); the final fault/HTTP run used three exact
pytest node IDs (3 passed, 8.61s). Interrupted/repeated checks are not included
in the distinct counts above. A third-party imghdr deprecation warning remains.

## Remaining acceptance

The current frontend still rejects table structure changes. Ribbon commands,
ProseMirror transaction capture, undo/redo, draft restoration and explicit
save/reopen before another same-table structural operation remain to implement.
There is no Microsoft Word/LibreOffice desktop acceptance; `desktopVerified`
stays false. ASGI native/artifact/grant repositories in this phase are doubles.
The prior PostgreSQL runs establish their earlier native SQL scope, not this new
structure flow against SQL or production tenants. Full application-image build,
deployed host authorization and broad source parity remain open. Feature flags
remain off; no merge or deployment occurs in this phase.

Final adversarial check: a source cell-property extension containing literal
`$&`, `$`` and `$'` reproduced a replacement-string interpolation defect in
the new adapter. XML is now inserted through replacement callbacks; the same
real-DOCX regression passed. The final package and Node22 offline HTTP case were
rerun after this fix; the recorded package SHA above is the final version. The
final 13-case probe checks whole paragraphs and cell properties with zero loss.
