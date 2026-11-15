# XLSX ordinary stacked bar/column Canvas — bounded acceptance

Current branch `work`, base1e4a0a34 plus preceding uncommitted Office work.
Reference: fixed GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c
`WorkbookVisuals.tsx:BarChart` (3002+ categoryTotal/segment/stackBase, and labels).
Previously grouping was written/read but the local Canvas always clustered bars.

## Delivered subset

Multi-series ordinary bar and column charts now share one category lane, draw
cumulative positive segment endpoints, and size auto numeric domains from category
totals. Percent stacks normalize each category independently, force0..1 quarter
ticks with0% display, retain original values for labels and preserve original
series/point indices in hits. One-series source grouping remains ordinary grouped.

Pinned source stacks clamp negative contributions to zero; this batch follows that
boundary and does not claim signed Excel stacks. Null/zero/nonpositive components
produce no artificial minimum bar/point; raw input/model/OOXML is unchanged. A
non-finite total visibly declines preview instead of fabricating a clustered chart.
Per-point colors, reversed axis/category behavior and existing grouped behavior
retain their prior host contracts. This is not proof of every source explicit-bound,
log/secondary-axis or manual-label-layout combination.

Stacked value labels use raw values, centered geometry and chart ink by default;
explicit text colors survive. Ordinary inside labels retain their previous white
default. No new save operation or schema. **Line, Area and Combo grouping remain
open**, as do full source axis/text/theme/marker/trendline/render parity.

## Fresh verification and retained failure history

- Behavioral RED8 failed /2 passed /145 unselected in
  `/tmp/xlsx-stacked-red-20261114.log`. Tests cover shared lane/endpoints/ratios,
  per-category percent ticks/manual-bound override, source negative clamp/null
  slots, source single-series rule, overflow and raw centered labels.
- First GREEN174 tests across renderer(155), value-scale16 and category-axis3.
- Scoped TypeScript initially found2 missing-required-reversed diagnostics, one
  new scale object and one fixture; both supplied explicit booleans without changing
  functional assertions. Final strict/noEmit actual module/test closure passed.
- Independent same-model static review found P2: forced inside labels inherited
  white on pale segments, whereas source excludes stacks from its white override.
  New pale-fill/default-ink/explicit-color test failed; fixed. Final directed run:
  **175 passed**, renderer156 + scale16 + category-axis3, with scoped typecheck green.
  This run verifies the fix and prior affected cases; no repeated project suite.
- New source hashes are recorded in vendor LOCAL-ADAPTATIONS-SHA256; original
  SOURCE hashes are unchanged. Source-binding.json matches the final tested files.

## Real browser, native pixels, mouse and OOXML

Artifacts `/tmp/xlsx-stacked-20261114/`: actual source writer/reader + renderer
fixture, final JS/metafile, browser.json/run log, four screenshots/downloaded XLSX,
verify.py and independent-readback.json. Chromium154.0.8037.57, pageerrors=[].
Worksheet values/geometry and Univer registration shell are injected; actual
OOXML writer/reader and Canvas extension are used, not a complete live Univer host.

Four scenes: column/bar × stacked/percentStacked. Source styles/metadata are read
from actual generated XLSX. Native pixel samples verify both series colors;
geometry confirms common lane/cumulative edges, per-category normalized heights
or widths and percentage ticks. Real mouse clicks select original series0/1,
point0. Browser Blob downloads are independently read by Python zipfile/XML and
openpyxl: grouping, direction and original caches unchanged by display normalization.
Normal raw cache [[2,4],[3,1]], percent raw cache [[1,3],[1,1]], not normalized data.

An initial browser assertion counted6 fills instead of4: the other2 were actual
8×8 legend swatches. Diagnostic geometry was retained in session output; final
runner separately records legendRects/allRects and validates the four real bar
segments. Product code/asserted geometry/pixel values were not relaxed to pass.

This is isolated component/engine/Canvas/file evidence, not production HTTP
adoption/revision authorization, real provider, complete import/export corpus or
native Microsoft Excel execution. Full frontend build/budget and whole project
suite were not rerun. No publication/download gate changed. No commit/push/merge/
deployment. Temporary HTTP server and engine node_modules link removed afterward.
