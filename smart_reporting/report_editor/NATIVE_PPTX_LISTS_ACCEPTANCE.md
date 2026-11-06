# PPTX Paragraph lists, direction and ordered history

2026-11-06; pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`.
This closes a bounded Paragraph command slice, not all PowerPoint capabilities.

## Original sources and implementation

The command inventory in `NATIVE_RIBBON_COMMAND_AUDIT.md` was checked against
upstream `RibbonHomeTab.tsx` (blob `aeb73bbf2400f7378eb224f2647d4f21770d3da8`).
Gallery wire characters/fonts and separate visual labels come from
`apps/slides/src/renderer/bullet-presets.ts` (blob
`504692a82ebde8cc49c9908005bc4ff5213527c9`). For example Wingdings wire `§`
is displayed as `▪`; the display label must not replace the stored character.
The adapter reuses the unchanged pinned `setElementParagraphFormat`.

Connected controls: char/number/none, seven glyph/font presets, sixteen Unicode
symbols and custom first Unicode scalar, nine numbering schemes, start 1–32767,
three hanging-indent presets and custom pixels, five relative sizes, ten colors
and custom color, level ±1, LTR/RTL, plus existing alignment/spacing. Picture
bullet upload is individually disabled with an explanation. This applies to all
paragraphs of a selected editable top-level text/shape, not caret ranges,
tables or grouped text. Source mixed/unset values are not fabricated defaults.

The strict Python and bridge schemas reject unknown fields and illegal values.
The inspector exposes actual list state separately from existing spacing state,
including explicit versus inherited hanging indent. Drafts retain **ordered**
paragraph records: level clamping means +1 then -1 at levels 0/8 produces 0/7,
not the original 0/8. Merging records by target would lose that behavior.
Every intermediate result is checked for OOXML margin overflow. Restoring an
invalid sequence preserves storage and reports failure. Semantically unchanged
commands do not create Undo entries; 500 actual records requires saving before
adding more.

## Verification and independent observations

- Initial backend list/spacing selection: 70 passed. Subsequent focused boundary,
  table rejection, picture-relationship and explicit-hanging probes passed;
  repeated selections are not added into a fabricated unique total.
- Initial frontend selection: 49 passed; later affected color/projection and six
  boundary checks passed. TypeScript and Ruff passed.
- Independent review reproduced three defects: repeated absolute formatting
  created false Undo; 501 same commands overflowed the ledger; maximum hanging
  indent followed by level increase produced an unopenable draft. Four original
  independent repro checks passed after fixes, including 501 genuinely changing
  commands stopping at 500. These are behavioral checks, not copied assertions
  of the implementation.
- Real Chromium smoke modes `paragraph-lists` exercise `number`, `glyph` and
  `none`: native inputs, custom Unicode, galleries, direction, hanging indent,
  ordered clamping, colors, spacing, Undo/Redo, refresh, actual download and
  revision-2 reopen. Python-pptx and raw OOXML independently check output values;
  an untouched object's complete XML and original file bytes must remain intact.
- Existing `paragraph-spacing` browser mode is rerun against ordered history.
- Four-format ASGI plus real PostgreSQL acceptance is documented separately in
  `NATIVE_POSTGRES_ACCEPTANCE.md`; its PPTX file checks include numbering,
  start value, relative size, color, hanging indent and direction.

Browser reproduction, from `report_editor/frontend` after packaging the current
engine using `docker/package-office-engine.mjs`:

```sh
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-pptx-lists-runtime \
PPTX_SMOKE_MODE=paragraph-lists PPTX_LIST_VARIANT=number \
PPTX_SMOKE_EVIDENCE_DIR=/tmp/pr190-pptx-lists-number \
node smoke/pptx-native-save-smoke.mjs
```

Repeat with `glyph` and `none` and distinct evidence directories. Each emits
`source.pptx`, `downloaded.pptx`, `evidence.json` with file identities/readback.
Routes for browser authorization and revisions are substitutes; the packaged
file engine and downloaded bytes are real. No Microsoft Office desktop opening,
production tenant authorization, deployed TCP service or full clean-image
acceptance is claimed. Flags remain off. Valid generated-file downloads retain
the existing nonblocking validation contract.

## Recorded browser identities

| Variant | Source SHA-256 | Download SHA-256 |
| --- | --- | --- |
| number | `3ff0000e6d9f0fc754d989acb60615da0a7a0f913df05cd30b2f1d390655588c` | `e084e089c49e3bc1e58c60986909e2f89c393bbf9f9fffdf5da954ae8d9395f6` |
| glyph | `213ee0b17e464a05beaad61315e3139573c204096b6dd79eea6d1b3c9c3416d0` | `8e083f435af46e758e0f56fbab508e3f5b57b7807cd7b1901f154e72427db608` |
| none | `42ead83163cc71d7911a921115c5540ddd6d674127ed02bbdb64205dd63c8470` | `e03aa45e16e90df375dd009f95e945ebd5e99b5a46436f95591c65e8d6f39a66` |

All three list browser cases passed. The first `none` attempt timed out waiting
for the canvas after refresh; a separate rerun passed without a product change.
Its failed log is retained alongside the successful run; no cause is asserted
from a timeout alone. Both final production builds, actual budget and budget
contract checks passed; the final affected ribbon/helper selection passed 23
tests after source glyph-label correction. Third-party chunk warnings remain.

The affected `paragraph-spacing` browser regression also passed with ordered
history: revision 2 download/reopen, 200% line spacing, 12.5/0pt before/after,
source bullet/RTL and untouched-object XML preservation.
