# Native Ribbon command audit — PR #190

Audit date: 2026-11-05. Baseline PR head: `0017ff7a22cb7931eb8dc387b0eb98b14601d933`, base `d0a683c11a9b4c068c8d91fcf385fd7f040c17b9`. Findings below include the current uncommitted custom-size implementation. They are a bounded source/adapter audit, not a certificate that all four formats have complete command parity or that browser acceptance passed.

## Primary sources and method

- Fixed upstream: `genspark-ai/genoffice@f8c17004fb730df11f0f743164ffd8b4281bb38c`.
- Read the actual upstream [`apps/slides/src/renderer/components/Ribbon.tsx`](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/slides/src/renderer/components/Ribbon.tsx) through GitHub `fetch_file` with this explicit ref. The returned Git blob SHA is `e2c8325f4c544a3c996e62dfee8b82dbcaf6de6b`. The local component manifest records an upstream SHA-256 of `6a261cf18bbdbf2b39fa51add3d30383a10ded4a072303e0012cb7e5cde00aba`; that SHA-256 was not independently recomputed from the remote response in this audit.
- Independently ran `sha256sum frontend/src/vendor/genoffice-slides/slide-size.ts` from the report-editor directory: `4f428b6e000b405ccaf2034be859b4de1a86a95641da747cd70e1b51467fe27a`, matching the pinned helper manifest.
- Traced source handler identity, rendered command declaration, runtime gating, draft operation and strict API/bridge boundary. Read the implementations rather than treating the plan or source-action attribute as proof of behavior.
- Performed a small executable counterexample for absolute size versus aspect-ratio labeling. No broad/full test suite was repeated for this documentation task.

## PPTX Design / Slide Size inventory

Paths in this table are relative to `smart_reporting/report_editor/frontend/src/`. Upstream line numbers refer to the fixed file linked above, not the local adapter.

| Source action | Fixed-upstream behavior | Local adapter and operation | Audited status |
| --- | --- | --- | --- |
| Preset 16:9 / 4:3 / A4 / A3 | Ribbon lines 1981–1996, `presetSize(key, isPortrait(deckSize))`, then `onSlideSize(cx, cy)` | `slides-native-ribbon.ts` command `slideSize`; `slides-main.ts` `case 'slideSize'`; one `editSlides.slideSize` pair | Connected. Preserves orientation. This source audit does not independently certify its browser/file acceptance. |
| Landscape / portrait | Lines 2005–2016, available whenever `deckSize` exists; swaps the two current axes without selecting a preset | `slideOrientation`; UI uses `setSlideOrientationEnabled(isStandardSlideSize(size))`, handler repeats that preset-only guard | Confirmed parity gap at audit snapshot: legal custom dimensions cannot be rotated directly even though current API/bridge accept any legal dimension pair. Selecting a standard preset first changes physical size. |
| Custom Slide Size | Lines 2023–2029 invoke `onCustomSlideSize()` | `customSlideSize` opens `slides-size-dialog.ts`, then one `editSlides.slideSize` pair | Connected implementation, acceptance tracked separately. At audit snapshot its `data-source-action` is incorrectly `onSlideSize`, obscuring the source entry handler. Final writeback can still delegate to `onSlideSize`; entry and writeback identities are different. |
| Use for New Presentations | Lines 2031–2045 call local `saveDefaultNewSlideSize(deckSize)` | `defaultSlideSize` is disabled with a reason explaining the lack of a blank-presentation creation flow | Explicitly unavailable is appropriate for the current host. Its `onSlideSize` source-action label is inaccurate; upstream does not resize the current deck for this preference action. |
| Current preset indicator | Line 1990 uses `matchSlideSizePreset(deckSize)` | `slides-main.ts` additionally falls back to approximate aspect ratio | Confirmed misleading state at audit snapshot: a non-preset absolute size can be labeled 16:9 or 4:3. Counterexample below. |

### Confirmed counterexamples and closure requirements

1. **Custom orientation gating.** Apply 20 × 25 cm (`cx=7200000`, `cy=9000000`); local orientation becomes disabled because the pair is not a fixed preset. Upstream would swap to 25 × 20 cm. Closure requires allowing a valid supported current pair (with editing lock retained), asserting one atomic draft edit, Undo/Redo, and saved/reopened axis preservation. Out-of-range source dimensions still need a clear unavailable state; do not bypass the strict range checks.
2. **Absolute-size indicator.** `cx=10000000`, `cy=5625000` has a 16:9 ratio but is not the pinned 16:9 preset `12192000 × 6858000`. The pinned helper returns `null`; the local ratio fallback returns `16:9`. Closure requires an explicit custom/empty indicator and a regression for equal ratios with unequal physical sizes.
3. **Source entry identities.** Inspect `[data-command="customSlideSize"]` and `[data-command="defaultSlideSize"]`: both currently report `onSlideSize`. Compare the upstream entry handlers above. Closure requires honest source identities and tests that distinguish opening a size dialog, changing the current size, and setting a future-document preference.

Executable reproduction of item 2, from repository root:

```sh
smart_reporting/reporting/slides_engine/node_modules/.bin/tsx -e "import { matchSlideSizePreset } from './smart_reporting/report_editor/frontend/src/vendor/genoffice-slides/slide-size.ts'; const size={cx:10000000,cy:5625000}; const ratio=Math.max(size.cx,size.cy)/Math.min(size.cx,size.cy); console.log(JSON.stringify({size,sourcePreset:matchSlideSizePreset(size),nativeDisplayedPreset:matchSlideSizePreset(size)??(Math.abs(ratio-16/9)<0.02?'16:9':Math.abs(ratio-4/3)<0.02?'4:3':'')}));"
```

Observed: `{"size":{"cx":10000000,"cy":5625000},"sourcePreset":null,"nativeDisplayedPreset":"16:9"}`. The reproduction intentionally shows the audited fallback expression; if production logic changes, check the source and update this record rather than treating this fixed expression as a test of current production code.

## Bounded cross-format checks

| Format / reviewed slice | Direct implementation evidence | Conclusion and limit |
| --- | --- | --- |
| DOCX pending command groups | `docx-ribbon.ts` sets pending buttons disabled, title/aria-description reasons; only the supported pagination-preview callback is enabled in this generic pending-group path | No enabled-but-unhandled command found in this path. This does not cover every React Home/Insert/Layout callback or every contextual command. |
| XLSX adapted ribbon | `workbook-ribbon.ts` disables actions with no mapped command or a registered `disabledReasons` entry; handler rejects those reasons before mutation | Explicit unavailability mechanism exists. Runtime success and persistence of each enabled command were not all verified here. |
| XLSX source contextual coverage | The top-level `tabs` list contains Home, Insert, Page Layout, Formulas, Data, Review, View; no Chart Design contextual tab is mounted by this adapter | The plan already admits incomplete contextual Chart Design. Task 6 cannot be marked complete from the current adapter. |
| PDF Page group | `pdf-page-ribbon.ts` marks rotateLeft, rotateRight, delete and reverse enabled; `pdf-main.ts` maps each to an operation and disables deletion/reverse when no valid surviving-page choice exists; other source items use per-command disabled reasons | All four advertised Page commands in this bounded table have handlers; no static missing-handler defect found. No independent file roundtrip performed by this audit. |

These checks deliberately do not claim a percentage of global command parity. Counting controls without accounting for option galleries, context state and source handler semantics would create false precision.

## Evidence and inventory debt

- `NATIVE_RIBBON_PLAN.md` references `.superpowers/sdd/NATIVE_RIBBON_PLAN/task-3-brief.md` and format briefs, but `.superpowers/` and those briefs were not present in this checkout (`rg --files --hidden /workspace /tmp` found no matching briefs). A missing local process artifact cannot support a reviewer-reproducible command inventory. Move the authoritative inventory into tracked repository files or retain explicit missing-evidence status.
- The design's initial snapshot says FindReplace/Drawing/Table presets are not registered; `workbook-main.ts` currently registers all three at runtime. Treat that design row as historical architecture context, not current executable status.
- Source IDs are tracing aids. A source ID alone proves neither semantic equivalence nor execution, persisted output, authorization or production deployment.
- The root task is separately diagnosing a browser input failure; this static audit neither attributes that failure to application code nor treats unit/build success as browser acceptance.

## Next bounded acceptance step

Resolve the three PPTX size discrepancies, then record the actual targeted test and browser/file evidence against the resulting source state. Continue inventory tab by tab from fixed upstream source, including omitted galleries and context-state predicates. Keep full source parity, clean/offline image and production-scope acceptance open until their own evidence exists.

## Independent follow-up review: three source-level discrepancies closed

Date: 2026-11-05, same PR baseline plus the root worker's current uncommitted fixes. This section supersedes the earlier snapshot's open source-level findings; it does not erase their original counterexamples.

| Finding | Reviewed change | Independent conclusion |
| --- | --- | --- |
| Custom orientation was preset-only | `slides-main.ts` now uses `isWritableSlideSize`, checking integer coordinates and the pinned `MIN_SLIDE_EMU`/`MAX_SLIDE_EMU` bounds; both the rendered orientation availability and its command handler use this predicate. `slides-native-ribbon.ts` now gates on `hasWritableSlideSize`, retaining `locked` and an explicit out-of-range reason. | The static restriction to preset dimensions is removed without widening writes beyond the strict numeric range. A valid custom pair can swap axes; an invalid source pair remains unavailable. |
| Aspect ratio mislabeled custom dimensions | `renderInspector()` now uses only `matchSlideSizePreset(size) ?? ''`. The ratio approximation is absent. | The confirmed `10000000 × 5625000` counterexample no longer takes a native ratio fallback. The unchanged source helper's absolute-size tolerance still defines preset recognition, as upstream does. |
| Source entry identities were conflated | `customSlideSize` now records `onCustomSlideSize`; `defaultSlideSize` records `saveDefaultNewSlideSize`; current-size preset/orientation commands retain `onSlideSize`. | These now match the fixed-upstream entry points. Specifically, `onCustomSlideSize` and `onSlideSize` are upstream Ribbon prop callbacks; `saveDefaultNewSlideSize` is an imported/local preference helper invoked directly in the Ribbon, **not** a Ribbon prop callback. The default command remains explicitly disabled in this host. |

The follow-up also read the added native-editor regression `does not label custom dimensions as a preset just because the aspect ratio matches`, which restores the exact counterexample and swaps it to portrait while asserting absolute dimensions; the portrait custom-size history test now expects orientation to remain enabled. Those are relevant test assertions, but this reviewer did not rerun them or infer their execution from reading the source. The root worker's final validation record must supply the actual run results. `git diff --check` on the reviewed product/test paths passed.

No further confirmed product defect was found in this bounded follow-up. A small remaining evidence improvement is to assert `onCustomSlideSize` and `saveDefaultNewSlideSize` separately in the ribbon's source-identity contract; at the time of follow-up the existing ribbon tests did not contain those exact identities. This is an assertion-coverage observation, not a finding that the corrected current attributes are wrong.

Full Task 6, all-format command parity, actual browser typing, downloaded-file roundtrip and production-scope behavior remain outside this static closure. In particular, the root investigation's empty-page input counterexample means the prior browser symptom cannot be attributed to the size adapter solely from that failing smoke.

Root follow-up evidence: the custom/default source-entry assertions were added to `slides-native.test.ts` and the specific test passed (1 passed, 23 skipped). Four affected dimensions/state regressions also passed. The independent runtime/file evidence is recorded in `NATIVE_RIBBON_INPUT_DIAGNOSIS.md`; the custom-size ASGI case is recorded separately in `NATIVE_RIBBON_HTTP_EVIDENCE.md`. These close the bounded findings without completing the global inventory.

## Next bounded slice: PPTX Home Paragraph, plus font-step availability

This follow-up audits the **complete Paragraph source group**, not the entire Home tab or Font group. Baseline remains PR head `0017ff7a22cb7931eb8dc387b0eb98b14601d933` plus current local changes. It reads the fixed upstream sources directly:

- [`RibbonHomeTab.tsx`](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/slides/src/renderer/components/RibbonHomeTab.tsx), Git blob `aeb73bbf2400f7378eb224f2647d4f21770d3da8`, fetched at the pinned ref. Paragraph is lines 921–1315; the font-step buttons are lines 813–814.
- [`bullet-presets.ts`](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/slides/src/renderer/bullet-presets.ts), Git blob `504692a82ebde8cc49c9908005bc4ff5213527c9`, fetched at the same ref, to resolve the imported galleries rather than counting their parent button as one capability.
- [`ribbon-shared.tsx`](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/slides/src/renderer/components/ribbon-shared.tsx), Git blob `b2b0cd44ad5d1a110b59897c6dff34df73a25bf3`, to resolve the imported `TEXT_COLORS` choices.
- The previously cited fixed `Ribbon.tsx`, lines 1577–1587, to resolve `fmtBtn`'s real availability predicate and callback.

### Paragraph command/option/context inventory

Source group entry is disabled unless `editing || hasSelection`. It saves an active text selection before opening the group (lines 922–934). Most detailed list/spacing actions require `hasSelection`; alignment and direction also accept `editing`. The native host currently edits **all paragraphs of one selected editable text-bearing object**, not an inline text range. It requires `element.editable && element.text.trim()` and retains its save/revision lock. Those scope differences must not be described as complete text-selection parity.

| Fixed-upstream action and options | Source callback / validation / context | Native state and wire behavior |
| --- | --- | --- |
| Bullets quick action | Lines 949–959: `onParagraphFormat({bullet:'char'})`; requires selection | Missing from native Paragraph group; not represented by an individually disabled command. |
| Numbering quick action | Lines 961–971: `{bullet:'number'}`; requires selection | Missing, not explicitly disabled. |
| Decrease/increase indent | Lines 973–995: `{indentDelta:-1}` / `{indentDelta:1}`; requires selection | Both missing, not explicitly disabled. |
| Remove bullet | Lines 1000–1009: `{bullet:'none'}`; selected state compares `curBulletChar === ''` | Missing; native model does not expose corresponding current bullet state. |
| Bullet gallery | Lines 1011–1033: seven exact char/font pairs: `•/Arial`, `o/Courier New`, and `§`, `q`, `v`, `Ø`, `ü` in Wingdings. Callback carries `bullet:'char'`, `bulletChar`, `bulletFont`; current-state glyph uses `bulletRunText` to normalize symbol-font character codes | Entire gallery missing; a generic “Bullets” label alone would not establish these choices, font identity, or selected-state behavior. |
| Extra/custom/picture bullet | Lines 1036–1071 plus handlers 220–233: 16 Unicode symbols (`◆◇★☆✦➤➔→✓✗♦◉◎▸‣–`); free input uses first Unicode code point of trimmed text; picture uses desktop `window.slidesApi.pickPictureFile()` and `bullet:'blip'` | All missing. Picture needs a reviewed browser upload/identity equivalent or an explicit unavailable state, not an imported desktop handler. |
| Numbering gallery and start-at | Lines 1073–1103: nine `numType` values: `arabicPeriod`, `arabicParenR`, `romanUcPeriod`, `alphaUcPeriod`, `alphaLcParenR`, `alphaLcPeriod`, `romanLcPeriod`, `circleNumDbPlain`, `ea1ChsPeriod`; start-at handler uses `parseInt`, integer ≥1 | Entire gallery/start input missing; current native schema accepts none of these fields. |
| Hanging indent | Lines 1105–1137: 171450 / 285750 / 342900 EMU preset choices; custom input parses decimal comma as a dot, requires finite nonnegative px, rounds `px*9525` to EMU | Missing; do not equate native object x-coordinate/geometry editing with paragraph hanging indent. |
| Bullet size | Lines 1140–1160: `bulletSizePct` values 75, 90, 100, 125, 150 | Missing. |
| Bullet color | Lines 1164–1192: `TEXT_COLORS` choices `#000000`, `#5A5A5A`, `#FFFFFF`, `#C43E1C`, `#E97132`, `#FFC000`, `#4EA72E`, `#0F9ED5`, `#0A50A1`, `#7030A0`, plus native color picker; custom helper debounces `onParagraphFormat({bulletColor:hex})` in `Ribbon.tsx:1564` | Missing. The native Font Color control writes text formatting, not bullet formatting, so it does not cover this command family. |
| Align left / center / right / justify | Lines 1193–1216: `onAlign(align)`, active state compares `curAlign`; enabled while editing or selected | Four native `paragraphAlign*` buttons carry source action `onAlign`; handler writes `paragraphFormatting:[{slideIndex,elementId,align}]`. The strict API allowlist and bridge accept exactly these four alignments, then `setElementParagraphFormat` applies them to the selected object. Native active state currently reads its pending edit or the first inspected paragraph; mixed-range state is not independently certified here. |
| Left-to-right / right-to-left | Lines 1218–1238: `onDirection(false/true)`, active state compares `curRtl`; enabled while editing or selected | Both missing, not individually disabled. Text alignment is a different property and cannot stand in for text direction. |
| Line spacing | Lines 1241–1278: selected object required; `lineSpacingPct` options 100, 115, 150, 200, 250, 300 | Missing. |
| Space before / space after | Lines 1280–1308: `spaceBeforePt` / `spaceAfterPt`; Enter parses decimal comma, finite 0–500 pt | Both missing. Native DOCX spacing is a different format and does not establish PPTX support. |

For all missing entries above, current `native_office.py` requires paragraph-formatting records to have exactly `slideIndex`, `elementId`, `align`; `edit-pptx.ts` forwards only `{align}`. Thus the missing ribbon controls cannot safely be enabled merely because the upstream engine has a broader paragraph operation. A future implementation needs strict API fields, scoped engine writeback, restore/history state, actual-file readback and an explicit disabled explanation until that path exists.

**Inventory conclusion:** the four native alignment commands are mapped; all other source Paragraph actions above are absent rather than visibly unavailable with reasons. This is a confirmed remaining Task 6 inventory gap, not a claim of accidental data mutation. No source-control count or UI screenshot can close it. This follow-up deliberately does not implement those new capabilities.

### Confirmed no-target font-step affordance and repair

Before this follow-up, `fontSizeUp` / `fontSizeDown` were declared as active controls, but `updateTextFormattingState()` did not include them in its target-dependent disabled list. Creating a native ribbon with its initial `hasTextTarget=false` left both enabled; clicking dispatched the commands. `slides-main.ts` then called `updateSelectedTextFormat`, which returns immediately without an editable text target. The UI therefore advertised an executable command that silently did nothing.

The fixed upstream uses `fmtBtn('fontSizeUp'/'fontSizeDown')`; `fmtBtn` is disabled unless `editing` and calls `onFormat` only when editing. The native host intentionally adapts these actions to whole-object text formatting, so its appropriate predicate is a valid text-bearing native target plus the existing save/revision lock, not upstream's inline editing flag.

Repair approved by the root task: add both font-step command IDs to the existing shared text-formatting availability update. No new editor state, engine operation, dependency or source-vendor modification was introduced. The previously target-free dispatch test now covers: no target (disabled, no dispatch), valid text target (enabled, both callbacks dispatch), save lock (disabled), unlock with target (enabled), removal of target (disabled), and lock/unlock without target (still disabled).

Actual focused verification, from `smart_reporting/report_editor/frontend`:

```sh
npx vitest run src/slides-native-ribbon.test.ts -t 'gates upstream font-size'
```

Result: **1 passed, 15 skipped**, duration 971 ms. `git diff --check` passed on the changed product/test/document paths. No full format or repository test suite was repeated. This is state/dispatch verification; it does not establish browser/file acceptance for the omitted Paragraph families or all Font controls. The root task is responsible for ensuring its fresh image snapshot includes this product change.


## PPTX spacing slice closure (historical checkpoint)

The earlier Home Paragraph inventory was a source-state snapshot. Line spacing and before/after point spacing are now implemented through `onParagraphFormat`, with strict native API/bridge support and actual per-paragraph inspector values. Explicit fields are merged with alignment and restored records; missing/mixed/alternative units remain blank rather than defaulting. See `NATIVE_PPTX_SPACING_ACCEPTANCE.md` for 52 backend cases, frontend/independent-review scope, browser/file acceptance and the separate packaged-ASGI proof. Bullets/numbering/indent/direction entries above remain open; there is still no claim of complete source parity.


## Current Paragraph closure (2026-11-06)

The inventory above is retained as the **pre-implementation** source snapshot;
its “missing” states are superseded here. Bullets, seven glyph/font presets,
sixteen symbols/custom scalar, nine numbering schemes/start value, three/custom
hanging indents, five sizes, ten/custom colors, ±1 level and LTR/RTL now have
strict native API/bridge, ordered draft/history and actual-file readback.
Picture upload is individually disabled with its browser identity limitation.
Alignment and spacing share the ordered ledger. Mixed/unset state remains
explicit. Scope is all paragraphs of a selected top-level editable text/shape;
caret selection, table and group contexts are not covered.

Gallery display labels were checked against pinned `bullet-presets.ts`, blob
`504692a82ebde8cc49c9908005bc4ff5213527c9`, separately from its wire characters
(e.g. visible ▪ stores § with Wingdings). See `NATIVE_PPTX_LISTS_ACCEPTANCE.md`
for options, independent defect repros, browser/file evidence and limitations.
This closes the tracked Paragraph slice, not all Home, Font or Task 6 parity.


## Word Table Layout bounded frontend closure

Six existing source IDs now have guarded native writeback:
`table-insert-row-before`, `table-insert-row-after`,
`table-insert-column-before`, `table-insert-column-after`,
`table-delete-row`, `table-delete-column`. They reuse PM table commands and
retain source coordinates through canonical projection/draft replay. Controls
require an inspected safe source, a single cell, no same-table pending changes
and an editable/unlocked session. Other individual Table Design/Layout controls
remain disabled. This is not a claim of whole-table selection, continuous
structure transactions, merged/complex tables or all-source parity. All six
buttons and independent downloaded-file checks pass the browser fixture; see
`NATIVE_WORD_TABLE_ACCEPTANCE.md` for the original cases and boundaries.


## Parallel bounded command closures (2026-11-06)

| Task | Newly connected source family | Availability and preservation boundary |
| --- | --- | --- |
| Word | Home superscript/subscript, with baseline clearing | Anchored nonempty whole paragraphs; preserve mixed run/link properties; no caret/cell/new-paragraph claim. |
| Excel | Six `rotate:*` choices | Exact signed angle/OOXML conversion; source inheritance not modeled by the reader is explicitly rotation-readonly; direct reader defect fixed. |
| PowerPoint | Transitions Apply to All | Source indices, effect kind and per-page advTm only; speed/advance-click/sound/extensions/variants/AC that cannot be preserved are refused before batch staging. |
| PDF | Pages rotateAll | Fixed clockwise +90 applied to surviving source page IDs in one draft step; budget and existing preview/lock contracts retained. |

Each family has a dedicated acceptance record in this directory containing the
pinned original source/blob, exact callback/library path, runtime/browser/file
checks and remaining limitations. A connected bounded family is not evidence
that all four source inventories are complete. The upstream single-page
formatter metadata-loss case remains valid historical evidence; the native bridge
now preserves supported-source metadata through a thin adapter. See
`NATIVE_PPTX_TRANSITION_PRESERVATION_ACCEPTANCE.md` for actual-file/browser proof
and readonly boundaries. The bulk gate and incomplete overall inventory remain.


## PDF current-page crop closure (2026-11-06)

The formerly disabled `genoffice.pdf.page.crop` now opens four displayed margin
percentages for the current source page. Strict crop operations and PDF.js
viewports preserve source-space identity through rotations and reorder. Actual
file/browser/history/ASGI/Node22 evidence and remaining source all-pages/image UI
boundaries are in `NATIVE_PDF_CROP_ACCEPTANCE.md`. The Page Size command remains
disabled; this is not a complete Crop & Resize group or Task 5 closure.


## PDF CropDialog all-pages option (2026-11-06)

The source checkbox now applies displayed margins to all surviving page IDs in
one draft history step. Per-page current bounds and rotation are retained;
async preparation is atomic and the opener is guarded during pending work.
`NATIVE_PDF_CROP_ALL_ACCEPTANCE.md` supersedes the earlier all-pages UI gap.
Image drag handles and the separate Page Size command remain unavailable.


## PDF paper-size bounded closure (2026-11-06)

The earlier Page Size disabled inventory is superseded for capability-approved
sources: five pinned presets now call the unmodified upstream byte writer, with
actual-output preview and strict source/mixing gates. The UserUnit2 raw source
counterexample remains reproducible and unsupported sources stay readonly for
size. See `NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md`; arbitrary-source/desktop parity
and remaining Page/Form Design families are not closed.


## PDF selected-text markup and whole-format status (2026-11-06)

Home/Annotate four markup additions now share pinned selection/quads/matching and
real AP writeback. Pending marks toggle; saved matches are not duplicated and
saved removal remains explicitly unavailable. This supersedes earlier disabled
underline/squiggly/strikeout addition entries, not the complete source toggle/
delete behavior. See `NATIVE_PDF_SELECTION_MARKUP_ACCEPTANCE.md` and the separate
family-level `NATIVE_PDF_ALIGNMENT_STATUS.md`; neither disabled controls nor206
mechanical App callback nodes are counted as completed source parity.


## PDF View source audit correction and reading closure

Fixed App viewNavGroup also has comments, comparison and attachments. Their
previous omission means the five-entry native list was not a complete source
inventory; all three were first inventoried as disabled controls in source order. The later
comments continuation below enables bounded note reading/navigation. Night
reading and18-step10–800% zoom/status/wheel/DOM-anchor behavior are accepted in
`NATIVE_PDF_VIEW_ACCEPTANCE.md`; those three families, reading-position persistence,
complete shortcuts and every source fit/layout rule remain open. No whole-View
completion or disabled-control parity credit is claimed.


## PDF saved-markup toggle follow-up

Home/Annotate now follow pinned pending-first then one-saved match semantics.
Safe four-type saved marks can be removed with immutable source/page/ordinal ID
and dictionary digest, history and actual preview/download. The original disabled
removal checkpoint is superseded only for these bounded sources. Linked replies/
popups/structure, direct objects, signed/XFA and unreadable sources stay readonly;
arbitrary annotation commands are not credited. Evidence: `NATIVE_PDF_MARKUP_REMOVAL_ACCEPTANCE.md`.


## PDF occurrence search follow-up

Home previous/next now address individual source matches, with case/whole-word
modifiers and counts; View search and Ctrl/Meta+F focus Home search. Pinned
search.ts and ui/find-text.ts algorithms/hash manifests are retained. The inline
search adapts the floating source bar; OCR and full contextual/layout parity are
not credited. Details: `NATIVE_PDF_SEARCH_ACCEPTANCE.md`.


## PDF existing sticky-note follow-up

Safe saved Text notes gain per-page edit/delete controls with strict source identity,
modal Apply/Cancel, original-object Contents/M updates and actual preview/download.
This closes a bounded existing-note gap; it does not credit pending-note/reply/thread
commands or full comment/sidebar UX. Raw XFA is censused before pdf-lib getForm's
side effect. See `NATIVE_PDF_SAVED_NOTES_ACCEPTANCE.md`.


## PDF pending sticky-note follow-up

Pending setNoteContents/removeDrawing source behavior now maps to updating/removing
the exact existing native addition record. The local adaptation binds the entire
draft snapshot plus index rather than introducing a backend/local-ID protocol.
Per-page pending controls support history and reopening as saved notes; threaded
context/sidebar and pending-only actual preview are not credited. Evidence:
`NATIVE_PDF_PENDING_NOTES_ACCEPTANCE.md`.


## PDF pending-note actual preview/date follow-up

Pending-only preview now renders actual output and actual PDF annotation contents.
createdMs is staged once; verified appended note dates use canonical UTC and old
untimed drafts retain unknown dates. Pinned AP/writer/round2 behavior is preserved,
with explicit append-count/payload drift refusal. This closes the prior preview/
time gap, not replies/threads/sidebar parity. Evidence: `NATIVE_PDF_NOTE_PREVIEW_ACCEPTANCE.md`.


## PDF whole-document comments continuation (2026-11-09)

View comments now reads/navigates Text-note roots/replies across surviving pages,
with body/author filter, current-page/time ordering, exclusive sidebar state,
exact existing-card navigation and existing safe mutation controls. Readonly
sourceRef is an exact PDF.js reference join, not an accepted mutation field.
Per-document cache, partial-page retry, draft/document cancellation and immediate
preview list clearing have targeted fault/timing evidence. Replies/complex notes
remain readonly; comparison/attachments and complete source popup/persistence UX
remain open. See `NATIVE_PDF_COMMENTS_ACCEPTANCE.md`; no whole-View/PDF claim.


## PDF existing attachment read/export continuation (2026-11-09)

The View attachments entry now reads saved attachment metadata/content through
PDF.js and offers user-triggered browser downloads from the authorized PDF.
Internal Map IDs, not filenames, bind bytes; empty streams are valid, unreadable
content shows explicit retry. Sidebar/document lifecycle does not create edits.
This supersedes the completely unavailable read/export checkpoint, not the pinned
source's add/remove/desktop workflow. Comparison and remaining source controls
stay open. Evidence: `NATIVE_PDF_ATTACHMENTS_ACCEPTANCE.md`.


## PDF reading-position continuation (2026-11-09)

Reading-position persistence is now connected through unchanged pinned view-state
helpers, scoped immutable source identity, actual DOM rows and guarded two-frame
restoration. Custom zoom/basic fit reopen, reorder, readonly and source/preview
separation have browser evidence; source Ctrl-wheel/search/comment priority stays
intact. Selection and scroll are distinct. This supersedes the wholly missing
reading-position checkpoint, not full fit/resize/keyboard/View parity. See
`NATIVE_PDF_READING_ACCEPTANCE.md`. Budget applies to Standard output only.


## PDF row fit and continuous reflow (2026-11-09)

Fit Width/Page now constrains every retained canvas in independent source-paired
rows, adapting unscaled native borders/headings/gutters. Resize/sidebar/layout/
rotation/deletion and actual preview reflow preserve view/selection; manual zoom
wins obsolete fit work. Unchanged form controls preserve pending input and focus.
Seven new cases,one new compound browser scenario,five affected browsers and
independent file readback pass. Full desktop side-note margin/host layout and other
remaining View commands are not closed. See `NATIVE_PDF_FIT_ACCEPTANCE.md`.


## PDF sidebar sizing/thumbnail lifecycle (2026-11-09)

Shared source-bounded pane width now supports pointer and keyboard, best-effort
persistence, cancellation and exact style cleanup. Thumbnails reuse committed
rasters during drag and lazily manage per-document/page image/task lifetime.
Immediate pagehide during reflow preserves latest fit intent. A30-page/DPR2 browser
scenario,affected tests and independent files verify bounded behavior; no full
source thumbnail overlays/context or desktop layout claim. Evidence:
`NATIVE_PDF_SIDEBAR_ACCEPTANCE.md`.


## PDF bounded attachment writing (2026-11-09)

The existing attachment pane now stages local file additions, exact saved-file
removals/keep and pending cancellation, using NativeDraft history and actual
output preview. The pinned flat-tree writer is unchanged; native validation adds
identity/budget guards, encoded name-byte ordering and post-save content checks.
This closes only safe flat-tree add/remove; complex/shared/associated/protected
sources remain read/export-only. Removal is not secure erasure. New browser,
engine/service and independent file evidence: `NATIVE_PDF_ATTACHMENT_WRITE_ACCEPTANCE.md`.


## PDF saved flat-root reply writing (2026-11-09)

Safe saved roots now expose a separate reply capability, including roots with
existing standard flat replies whose bodies remain readonly. Exact-source
identities replace source rect/content fallback at the public boundary; pinned
note drawing is retained and output must contain the precise IRT parent and RT/R.
Pending replies reuse draft history/modal editing and source/preview isolation.
New counterexamples prove missing/wrong-parent output is refused. Pending roots,
saved-reply mutations and complex thread families remain open. See
`NATIVE_PDF_REPLIES_ACCEPTANCE.md`.


## PDF pending-root reply identity/lifecycle (2026-11-09)

The existing thread reply entry now supports roots still in the immutable-source
draft. First reply assigns one32-hex local identity and stages the reply in one
history transaction. Editing preserves identity; deleting the root removes its
children atomically. Native writes use the unchanged localId/replyToLocalId branch
and verify actual fresh references rather than rect/content matching. Legacy
unknown dates remain unknown; protected/ambiguous sources and complex thread
families stay outside the write boundary. No new Ribbon-command count is claimed.
See `NATIVE_PDF_LOCAL_REPLIES_ACCEPTANCE.md`.


## PDF saved flat-leaf reply mutation (2026-11-09)

Existing editNote/removeNote now accept exact safe saved reply identities derived
from the full source graph. Parent/sibling ambiguity stays readonly; body edit
changes only Contents/M and leaf removal releases only a proven unshared dictionary
to avoid stale inbound IRT. Source/preview/readonly/capability guards cover pane
and page-card actions; ordinary note editing remains independent. The new source
annot-delete.ts is a pinned primary reference, not a claimed executed PDFium path.
See `NATIVE_PDF_SAVED_REPLY_EDITS_ACCEPTANCE.md`; no new Ribbon count is claimed.


## PR #210 Table Design 与保真修复

直接核对固定 Ribbon.tsx 的 onEditTableStyle（底纹与 all/none 边框），逐字节复用 table-shading-colors.ts。原生只接通整表底纹/无填充及黑色 1pt 全部/无边框，preset gallery 与 cell-range 保持未开放。引用图涂黑、N 合 1 可见外观、表单拆分限制与最终段落动画的真实文件反例/回归见 `NATIVE_PR210_PRESERVATION_ACCEPTANCE.md`。
