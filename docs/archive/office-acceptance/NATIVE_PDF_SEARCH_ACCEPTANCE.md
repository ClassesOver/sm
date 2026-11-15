# Native PDF source-search acceptance

2026-11-06. Replaces page-only search navigation with bounded source-compatible
occurrence search. This does not implement OCR or complete whole-PDF parity.

## Original materials and method

Fixed GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- `apps/pdf/src/renderer/search.ts`, blob `6c768b27158cea839c35a1ed1cc51a600d5cbedc`:
  index actual PDF.js items without invented spaces, preserve EOL, cache extraction
  per document, match without overlap, interpolate per-item boxes, cap1000.
- `packages/ui/src/find-text.ts`, blob `3022b89971c05f55890b89a81ef34b1e9e533d84`:
  length-preserving case folding and Unicode letter/number/underscore boundaries.
- Fixed App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`,
  lines2657–2725 and10758–10830:200ms debounce, case/whole-word controls,
  current/total count, cyclic previous/next, Enter/Shift+Enter/Escape,
  deleted-page filtering, first-hit positioning and current-match decoration.

The two algorithm modules are copied with their algorithms unchanged. Adaptations
are a prominent provenance notice and local helper import. The adjacent
`genoffice-pdf-search-source.json` separately records upstream/local SHA256 and
exact adaptations; GenOffice LICENSE/NOTICE remain available in pdf_engine.
Native UI retains its existing inline Home search; View search and Ctrl/Meta+F
activate Home and focus/select that field. Escape clears the inline search and
returns focus to the viewport, rather than closing a desktop floating search bar.

Each match now has original source page identity and individual rectangles rather
than one page-level boolean. Search overlays distinguish the current occurrence,
leave selectable text nodes intact and transform using PDF.js viewport geometry
for the actual CropBox, rotation and UserUnit. The source uses proportional
interpolation, not exact glyph geometry; rotated-run boxes retain that source
approximation. CJK whole-word mode intentionally retains substring behavior,
while Latin word boundaries reject longer words and underscores. Search trims
outer query whitespace as the source does; no regex/normalization/OCR is invented.

Deleted pages disappear from navigation; source-document order is retained when
pages are reordered, as in the pinned search index. Actual-output preview indexes
its own bytes/order and maps them back to original source page IDs. Returning to
the original reuses its cached index. Query/options reset to the first match;
zoom/layout refresh preserves position without forcing another scroll. Navigation
requests during asynchronous page-card refresh are deferred until the target
holder and viewport mapping exist. Timers/listeners/index cache are disposed.

## Verification

Eight new focused cases cover repeated occurrences and boxes, split text items/
real EOL, Turkish dotted I/supplementary characters, case/Unicode whole-word/CJK,
non-overlap/global cap, geometry-free/scanned pages, extraction cache/preview
identity and source hash manifests. Seven affected zoom/outline/View cases pass.
Checks were split across focused runs, not counted again after retries. Initial
test expectations were corrected for floating-point interpolation and Vite's
rewritten import.meta URL; algorithms were unchanged.

Production-static Chromium checks real repeated-run occurrences, separate boxes,
current/total count and wrap, Enter/Shift+Enter, case/whole-word toggles, no-result
state, Escape, View focus and Ctrl+F, draft invariance, deletion/undo/reorder,
actual packed-engine preview and original-page identity, readonly navigation,
and unchanged original download SHA. Fixture includes a rotated page, UserUnit2,
offset CropBox and a blank page. Auth/revision routes are substitutes, and actual
PDF.js/packed PDF engine execute; production permissions/SQL/desktop are not proven.
An initial browser run exposed navigation while preview cards were still rebuilding;
that product race was fixed by retaining the pending navigation request. Raw failed
runs, including the initial fixture syntax correction, are retained.

Final Standard32.66s/Slides32.34s builds include strict frontend typing and
actual bundle budget checks. Backend and packaged runtime are unchanged; no old backend/Node22/SQL
checks are counted as new verification. Final browser/download identities and
independent pypdf text counts are recorded in the evidence archive. Accepted source/download
SHA256 is `5877a796abe4d66454d2c265b3af3967ff3197a722647863b194d5b4a8f4bb3b`,
actual preview SHA256 is `01603d33b8ad834c785728ce8eb5dbbd1408adcbd1fa57254cc6fe2a5199e333`.
pypdf independently finds6 case-insensitive,4 whole-word and3 case-sensitive
whole-word matches and verifies reversed actual-preview pages and saved underline.
Archive:
`/workspace/scratch/pr190-pdf-search-evidence.zip`.

Remaining: OCR/auto-OCR, source floating-bar placement and contextual behavior,
exact glyph geometry for rotated/complex text, all source shortcut combinations,
full application image and desktop/deployed acceptance. The broader matrix is
`NATIVE_PDF_ALIGNMENT_STATUS.md`; flags remain off.
