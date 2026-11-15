# XLSX Line/Radar source stroke alignment — bounded acceptance

Base `1e4a0a34`, existing branch `work`; follows the previous uncommitted Scatter
fallback batch, which is left unchanged. Reference is fixed GenOffice
`f8c17004fb730df11f0f743164ffd8b4281bb38c`, freshly fetched WorkbookVisuals.tsx:
`lineStroke`, `LineChart` and `RadarChart`. Complete reference retained in the
artifact root below. Local reader already extracted source stroke fields; local
Canvas ignored them for these two families.

## Delivered scope

- Line and Radar consume independent series lineColor and lineWidth. Fill and
  point colors remain independent. Source default widths are Line 3 / Radar 2.5.
- Explicit noFill, zero width and unresolved line colors do not invent a stroke.
  Existing markers, radar fill, data, geometry and labels remain as before.
- Invisible connecting segments have no synthetic series hit region. Visible
  thick lines and radar polygon edges have width-aware hit regions; point hits
  keep priority, and radar fill remains selectable even without an outline.
- Area/combo outlines, source marker visibility, radar label semantics, complete
  axis/font/theme styles and cross-family full visual parity are outside this
  batch. Source default values do not prove source SVG/host Canvas pixel identity
  across all sizes.

## Tests and review

Seven targeted tests failed before implementation (explicit stroke/width, hidden
stroke, defaults, invisible line hits); 133 pre-existing renderer cases were
unselected. After the first implementation all 140 renderer tests passed.
Actual OOXML→reader→renderer tests then found two fixture setup errors (missing
required chart.title); only the fixture was corrected, and those two passed.
The setup failures are not product RED or green evidence for source fidelity.

Independent same-model static review identified a P2: a thick radar outline's
paint outside the fill could not be selected. Added a failing outside-edge test
(1 failed / 1 passed), then shared segment-distance logic for line/radar. Final
four-file directed run: **174 passed**, including **145 renderer tests** and 29
selection/element-hit/object-interaction tests. Strict/noEmit typecheck of renderer,
its actual import closure and tests passed with project-compatible ESNext/DOM libs.
Diff whitespace check passed. No project-wide suite repeat or full frontend build.

## Native Canvas and actual mouse evidence

Artifacts `/tmp/xlsx-line-radar-20261114/`: original/final browser fixtures, bundles
and metafiles, pinned source, source-binding.json, browser.json, thick-browser.json,
six screenshots and final thick-outline screenshots. Browser Chromium
154.0.8037.57, pageerrors=[]. Actual reader and chart-render extension paint native
Canvas from generated OOXML style fixtures. Only the Univer extension registration
shell is stubbed; worksheet values/geometry are controlled fixtures, not a complete
Univer grid or production editor. No production save/download claim is made.

Before the hit-only correction, six pixel scenes passed: Line/Radar × explicit
7px purple outline/noFill/zero. Explicit source outlines produced 3477 / 2297
opaque purple pixels respectively; noFill/zero produced zero. Fill-colored point
pixels remained. The compiled pre-fix bundle is retained as app-before-hitfix.js.
This six-scene run is not mislabeled as rerun on the final hit-fix code.

After the hit correction, final-source browser recheck covered two affected radar
scenes only. Real mouse click at (351.9615,126), 8px outside an edge midpoint:
20px outline had actual purple pixel [160,32,240,255] and returned series:0; noFill
had white pixel and returned chart. Final source hashes are recorded separately.
These are direct rendering/hit checks, not full Microsoft Excel rendering parity,
real-file import/export, native editor adoption, production HTTP authorization or
server-restart recovery acceptance. Neither source OOXML bytes nor writer protocol
was modified by this renderer batch.

Initial setup attempt used wrong repository-relative paths and hit the previously
removed engine dependency link before any tests ran. Corrected the working directory
and restored the same temporary frontend node_modules link; no dependency/lock change.
Tests use existing Vitest 3.2.7, not a fresh engine toolchain install. Link and local
server are removed afterward. No commits, pushes, merges or deployment.
