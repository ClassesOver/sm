# XLSX Scatter first-series label fallback — bounded acceptance

Base: `1e4a0a34`, branch `work`. User requested XLSX alignment after the gap review.
Reference: GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`,
[charts.rs:598–641](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/sheets/native/xlsx-engine/src/visuals/charts.rs#L598-L641), freshly read through GitHub. An initial guessed path returned 404; the documented canonical path succeeded.

## Delivered behavior

- Match pinned root/first-series mode precedence: root mode wins unless absent/none;
  only the first series supplies fallback. Scatter renders only final `value` mode.
- Read namespace-qualified direct flags only. Point/extension/foreign flags and later
  series do not switch on global labels. Delete and percent combinations retain
  source precedence rather than being flattened into value.
- Preserve all source series. If deleting root labels would reveal first-series
  value labels, reject only `dataLabels: none`. Enabling value, unrelated edits,
  first-series none/percent/point-only and later-series labels remain supported.
- Chart format pane and design dialog explain the restriction, disable only the off
  option, guard synthetic submissions, and reset on another chart. The shared
  engine guard also applies to presets/AI and rejects an atomic batch before output.

Chosen tradeoff: conditional rejection preserves source series overrides. A reader-only
change would silently make off ineffective; deleting series overrides would lose source
settings. This batch does not introduce a series-label editing UI or promise every
imported label combination can be turned off.

## Fresh verification

- Engine behavioral RED: 5 failed / 19 passed. After implementation, one remaining
  old expectation (`design.dataLabels` undefined for root value plus series detail)
  conflicted with the intended effective-mode projection; updated to value. No source
  series metadata or point overrides were removed to obtain that result.
- UI RED: 2 failed / 23 passed. GREEN: 184 tests across format pane, design dialog,
  renderer, presets and ribbon presets. Engine GREEN: 111 tests across six affected
  files. Two subsequently added alternate/default namespace cases passed separately
  (24 existing cases unselected); do not claim a single 113-test execution.
- Tests used the existing frontend dependency installation (Vitest 3.2.7) through
  a temporary engine node_modules link, not a fresh locked engine Vitest 4.1.11 install.
- Engine package strict typecheck passed. UI modules' actual import closure passed
  strict/noEmit with ESNext/DOM/DOM.Iterable, matching the project libraries.
- Full frontend typecheck failed in the current environment: missing sibling DOCX/
  PPTX dependencies (e.g. fast-xml-parser, @genoffice/pptx-engine, bidi-js) and related
  diagnostics. Log: `/tmp/xlsx-parity-frontend-tsc-20261114.log`. No full build claimed.
  First narrow command omitted the project's ESNext library and reported existing
  modal.findLast typing; corrected the command's libraries, not product code.
- Independent same-model reviewer found no important issues (static review; no
  independent test rerun). PDF edits were excluded.

## Real browser and file evidence

Artifacts: `/tmp/xlsx-scatter-fallback-20261114/` (`app.ts`, bundle, `browser.mjs`,
`browser.json`, screenshot, actual source/edited downloads, `verify.py`,
`independent-readback.json`). Chromium runs actual two UI components plus actual
read/edit engine in an isolated fixture. Both off choices disabled with explanation;
unrelated title edit succeeded; real browser downloads parsed independently using
Python zipfile/ElementTree. Only `xl/charts/chart1.xml` changed; source series subtree
and first-series value labels were preserved; all XML/rels parsed. Source SHA256
`e5f95ecf806f7f4295bcddc3810f493cd90465c97dd4753d5845ba508a2ec15c`, edited
`3ea5d605c228364eb8e21a8b1bc8e0bce0604dc8f9b12f1be83388a2574e59c4`.

Browser setup failures retained in session output: first bundle used JSZip's Node
entry and could not resolve stream; fixture switched to the existing browser bundle.
First browser assertion used Playwright isDisabled on option despite the actual
native disabled property being true; probe preserved source/DOM evidence and runner
now reads option.disabled. Next attempt read hidden dialog defaults before async
readWorkbook/open completed; runner now waits for visible control. No product change
or relaxed functional assertion was needed for these harness corrections.

This is component+engine browser/file acceptance, not production HTTP authorization,
NativeDraft adoption, revision registration, server restart recovery, full source UI
parity or complete Microsoft Excel compatibility. No full test suite repeat, dependency
version change, commit, push, merge or deployment. Prior PDF changes remain untouched.
Original source hashes stay frozen; current engine/test overrides are registered in
UPSTREAM-PATCHES-SHA256.json. Temporary dependency link/services are removed afterward.
