# Word paragraph superscript/subscript continuation

2026-11-06; bounded Task 2 slice. The existing Home Subscript/Superscript controls
now apply whole-paragraph vertical alignment in source-anchored body paragraphs,
headings and list items. This does not establish caret-range or full Font parity.

## Original source and reused mechanism

Read the original fixed GenOffice `apps/docs/src/renderer/components/Ribbon.tsx`
at commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`, blob
`79c195ad6ac80ec0f0f2fc985cc0523da0d38ae2`. Lines 1986–1988 define
`toggleVertAlign(kind)` using `setTextStyle({vertAlign: sameKind ? null : kind})`;
lines 3929–3943 expose the two toggles. The pinned local `editor/marks.ts`
retains `docTextStyle.vertAlign`, and `convert.ts` retains the corresponding
Run field. The unchanged engine serializes the same Run/rPr representation.
No vendor, lockfile, global build configuration or feature flag changed.

The browser reuses Tiptap `setMark` over the complete anchored paragraph;
unrelated per-run font, color, emphasis, link and tooltip metadata survive.
The diff isolates vertical alignment from other text-style comparisons, so
mixed bold/italic/font runs are not flattened into the existing uniform-style
operation. A partially changed vertical range is rejected explicitly. Both
buttons show active state and support toggle-back to baseline, source locks,
readonly/new/empty targets and cross-paragraph selection refusal.

## Strict writeback and inherited-format counterexample

`setParagraphVerticalAlign` has exactly `kind`, `blockId`,
`expectedObjectSha256`, `value`; `value` is `superscript`, `subscript` or
`baseline`. The wrapper admits the kind; the bridge validates source identity,
fields and enum before applying the ordered batch. A standalone empty target
is rejected; preceding valid text replacement in the same batch can supply the
current text. Draft restoration validates fields, enum and source hash.

Baseline must be an explicit `<w:vertAlign w:val="baseline"/>`, not merely a
removed direct property. Otherwise a character/paragraph style can reintroduce
superscript after the requested clearing. The adapter inserts the explicit
baseline using the pinned `RPR_CHILD_ORDER` and `splitXmlChildren`, retaining
other rPr children and root attributes. Tests separately exercise inherited
character and paragraph styles, retain the unchanged superscript style
 definition, and independently verify the saved run's direct baseline override.

The frontend active-state projection follows direct formatting exposed by the
pinned Run→PM model. This slice does not certify display of inherited vertical
alignment in every source style or desktop Word layout. The explicit baseline
file protocol does neutralize inherited alignment; broader inherited-style
canvas parity remains separately reviewable.

## Recorded evidence

- Frontend: initial selection **70 passed** (10 new vertical cases, 45 existing
  operation cases, 15 existing Ribbon cases). One further quick-command Undo
  case passed separately: **11 distinct new cases / 71 distinct total**. The
  quick superscript→subscript Undo/Redo probe passed without adding a custom
  history implementation.
- Backend: **16 passed** initially. Baseline/inheritance/order selection then
  passed **4** cases, comprising two affected checks and two new inheritance
  checks. **18 distinct new checks** passed; reruns are not summed as new cases.
  Independent python-docx/lxml checks cover mixed runs, unknown rPr (`noProof`),
  pPr (`mirrorIndents`), source links/tooltip/plain style and all untouched ZIP
  files except normal document/core save changes. Invalid values/fields,
  stale anchors, empty targets and composed ordered replacement are included.
- Final strict bridge TypeScript, Ruff for new Python tests/wrapper, Node smoke
  syntax and diff checks passed. Shared frontend build is owned by the root
  integration task, not redundantly run by this slice.
- Real browser: **Chromium 154.0.8037.57** on isolated port 4193 with the final
  production-packed bridge completed superscript, subscript and explicit
  baseline saves/downloads/reopens through revisions **2/3/4**. Ctrl-Z/Redo,
  actual page reload/draft recovery, active/closed locks and fresh source
  revisions passed. Each actual download independently retains text, mixed
  styling, link tooltip/plain style, unrelated paragraph and ZIP files; source
  bytes stay unchanged. Deliberately failed validation retains Word downloads.

Final packed `dist/edit-docx.mjs` SHA-256:
`5eeaca8816655e43b0ca8fc41533c679554d485e1dd85b2251b88ddf75dce010`.
Final browser source SHA-256:
`7ce499456608c31b06b80123ab937de456334bf7db7475a66a642ac676466bff`.

| Revision | Value | Download SHA-256 |
| --- | --- | --- |
| 2 | superscript | `5822af3d3cb965cb7755a61cad402668c8750665dfb4a3279700e11fa5d1d421` |
| 3 | subscript | `a325f902408505b1b79f4fec39d7ee5c209575585f1ec8b6c61ddd0942278f1e` |
| 4 | baseline | `19b2c5717d7e049e9016bdc83d4f83ede0dbed6fa1392b30676a100872ed3db5` |

Artifacts: `/tmp/pr190-word-vertical-final-evidence/revision-1.docx` through
`revision-4.docx` and `evidence.json`. Logs:
`/tmp/pr190-word-vertical-front.log`, `-history.log`, `-back.log`,
`-baseline.log`, `-bridge-types.log`, `-final-browser.log` under the same
`/tmp/pr190-word-vertical` prefix. The initial browser run preceded the explicit
baseline fix; only the final run/hash table above is the accepted checkpoint.

## Reproduce and limits

From the repository root, after ordinary bridge bundling and packaging:

```sh
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-word-vertical-final-runtime \
DOCX_VERTICAL_SMOKE_EVIDENCE_DIR=/tmp/word-vertical-new-evidence \
node smart_reporting/report_editor/frontend/smoke/docx-vertical-smoke.mjs
```

Browser authorization/revision routes are substitutes; the file engine and
actual downloaded bytes are real. This slice adds no independent deployed HTTP,
real-SQL/grant-storage or Office desktop acceptance for the new operation. No
new cursor-range, table-cell, unanchored-paragraph or complex-inline support is
claimed. Source-linked paragraph text replacement keeps its existing explicit
restriction. Remaining Word command families and global Tasks 2–6 stay open.
Feature flags remain off; no merge or deployment was performed.


Root integration also executed the mixed-run baseline case and both inherited
style baseline cases through the production-packed bridge in Node22, read-only,
network-none container: 3 passed (1.67s). Python/source are explicit read-only
mounts; this is a mounted-runtime probe, not a full application image. The two
affected existing Word-table/history frontend cases passed after integration.
