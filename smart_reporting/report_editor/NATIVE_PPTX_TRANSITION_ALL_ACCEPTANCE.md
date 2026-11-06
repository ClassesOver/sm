# Native PPTX Apply to All: effect, identity and file acceptance

2026-11-06; bounded Task 4 continuation. This connects the existing Transitions
→ Timing → Apply to All source action. It does not complete PowerPoint Ribbon
parity, add transition sound/duration controls, preview playback or desktop
certification. Feature flags are unchanged.

## Primary source and exact adaptation

Pinned GenOffice: `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

| Original source | Observed contract |
| --- | --- |
| `apps/slides/src/renderer/components/Ribbon.tsx`, Git blob `e2c8325f4c544a3c996e62dfee8b82dbcaf6de6b`, lines 2055–2087 | Individual effect calls `onTransition(kind,false)`; Apply to All calls `onTransition(transition,true)`. Both need a document, not a selected text object. |
| `apps/slides/src/renderer/App.tsx`, blob `414eb2933e5f87434db874e8951f44a7e833beec`, lines 1752–1756 and 3390–3393 | Delegates to animation actions; preview is started only for a single-page effect, not Apply to All. |
| `apps/slides/src/renderer/animation-actions.ts`, blob `90553c19b24086f1a6bcec7b8ed11765bd6f5c40`, lines 11–25 | Desktop action sends `slideIndex:-1` for all slides, then updates transition/dirty state. The desktop handler is not imported into the browser. |
| Existing pinned `pptx-engine/src/index.ts:setSlideTransition` and `generate.ts:patchSlideTransitionXml` | Existing native writeback changes the effect and retains each page's own `advTm`; `none` removes the effect while retaining automatic advance. No vendor source changed. |

The browser expands this intent into the existing strict, nonnegative,
source-indexed `editSlides.transitions` records. It copies the **active effect
kind**, whether read from the source or pending on that page. It does not copy
the active page's automatic-advance time onto other pages. Inspection now explicitly rejects batch application when any source target has
additional transition settings: speed/duration, click-advance attributes, sound
actions, extension children, unmodeled effect variants, or AlternateContent.
Only the effect kind/generic or pinned default variant and legal per-page
`advTm` are accepted. Missing safety metadata disables batch application rather
than assuming an older engine is safe. The handler repeats this gate even if a
script dispatches a click on the disabled control; stored drafts remain intact.
Single-page transition writeback is unchanged and is **not** claimed lossless.

The adapter uses original slide indices even after visible reorder. Apply to All
writes one NativeDraft snapshot; repeated identical application does not add an
Undo step. All 12 existing kinds are supported. Loading/unavailable document,
saving, saved-revision and more-than-500-page states disable the button.
Text selection is not required. The tooltip explains effect-only scope and
per-page automatic-advance preservation.

## Restore boundary repaired

Real-file probing showed that a source `order:[2,0]` from a three-page deck is
rejected by the existing bridge (`slide_order_invalid`): this editor supports a
full permutation, not slide deletion. The old frontend could restore such a
draft and advertise editing until save failed. Restore now validates the complete
permutation, duplicate/out-of-range indices and transition records before mutating
view/history. Invalid storage remains intact with an explicit error.

Known absolute transition records may repeat a source index. Restore retains
last-write semantics and leaves the original stored request untouched; an
explicit Apply to All supersedes those effects atomically. This is different
from relative paragraph operations, whose ordered ledger remains unchanged.

## Verification actually executed

- **13 distinct new frontend cases**, plus **one affected source-action Ribbon
  case**, passed across focused selections. They cover source/pending effect,
  no text target, original identities under reorder, repeated-click Undo,
  NativeDraft Undo/Redo, true storage recreation, successful-save lock,
  invalid transition fields/effects/targets, invalid full permutations,
  older absolute-record ordering, 500-page boundaries and mixed-target unsafe/unverified metadata refusal. TypeScript passed.
- **20 distinct real-file checks** passed: each of 12 kinds on a reordered
  three-page PPTX, explicit rejection of partial order, six unsafe source cases
  (speed, click advance, sound action, unknown variant, extension and a single-
  Choice AlternateContent), plus one modeled default-variant control. Python-pptx and raw
  XML independently check effect kinds, original object XML, untouched timing
  XML, per-page `advTm`, presentation order and unrelated ZIP members. Ruff
  passed for the new backend test. No edit-request schema or shared Python file changed; inspect adds the batch safety flag/reason.
- The first partial-order probe intentionally exposed unsupported deletion; the
  test now asserts that rejection and the frontend rejects it on recovery. No
  engine behavior was relaxed. Early frontend harness mistakes (using a view
  `refresh` method that does not exist, and Vitest array rows being spread into
  callback arguments) were corrected; the final cases exercise actual draft
  arrays and the actual native history buttons.
- Chromium **154.0.8037.57** passed the complete browser fixture on port 4195:
  source fade → Apply to All → Undo; source push page moved to the first visible
  position; pending wipe → Apply to All → repeated click → one Undo restores only
  the single-page pending wipe; Redo; actual page reload/storage recovery; all
  page indicators; save revision 2; actual downloaded bytes/SHA; independent
  python-pptx/XML/ZIP readback; revision-2 reopen and fresh editable control.
- Initial browser fixture issues were a Home-only reorder button clicked while
  its panel was hidden, then a fixture incorrectly requiring every preview to
  have no operations. The final fixture switches panels and handles nonempty
  preview through the actual file engine; it does not weaken error checks.
  Browser page-error list is empty.

Accepted source SHA-256:
`b4fa8aece07b1533bc9ddb90ddf6447c4939e6f2ee03821851b59efffa14e8c8`.
Downloaded SHA-256:
`a174b367c0d7f30101a23a4a219012fa7d6bc4bb1c96cfab4939c3afc496c752`.
The downloaded order is source pages `[1,0,2]`, all effects are `wipe`, and their
individual advance times remain `[2000,1000,3000]` ms. Original object/timing XML
and unrelated package file bytes match the corresponding sources.

## Reproduce and evidence boundary

From `report_editor/frontend`, using the current production-packed Slides engine:

```sh
AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-pptx-apply-all-final-runtime \
PPTX_SMOKE_PORT=4195 \
PPTX_SMOKE_EVIDENCE_DIR=/tmp/pptx-transition-all-evidence \
node smoke/pptx-transition-all-smoke.mjs
```

The default browser binary is `/usr/bin/chromium`; override with
`REPORT_EDITOR_CHROMIUM_EXECUTABLE`. `source.pptx`, `downloaded.pptx` and
`evidence.json` contain actual file identities, strict submitted operations and
independent readback. Browser authorization/revision registration routes are
substitutes. The converter is the actual production-packed bridge. This is not
new PostgreSQL, deployed authorization, complete application-image browser,
Microsoft Office or slideshow-playback acceptance.

Focused test files are `frontend/src/slides-native.test.ts`,
`slides-native-ribbon.test.ts` and
`reporting/tests/test_pptx_transition_all.py`. Logs are
`/tmp/pr190-pptx-apply-all-{frontend,frontend-recheck,invalid-draft-tests,ordered-test,budget-test,file-tests,order-file-test,browser,types}.log`; the gated browser log is `/tmp/pr190-pptx-apply-all-gated-browser.log`,
with source/output/receipt in `/tmp/pr190-pptx-apply-all-gated-evidence`.
Gate file/frontend logs are `/tmp/pr190-pptx-apply-all-gate-files.log` and
`/tmp/pr190-pptx-apply-all-gate-frontend-recheck.log`; the final MC negative is
`/tmp/pr190-pptx-apply-all-ac-negative.log`.
The initial failed file selection contains 12 successful effect cases; the
separate corrected partial-order check passed once, without repeating the 12.
Final production frontend builds and budget checks are integrated once by the
root agent after all four parallel format tracks stabilize; they are not
claimed by this per-format agent.


## Confirmed formatter limitation and the new refusal boundary

A real source PPTX with `advTm=1000`, `spd=slow`, `advClick=0` and a sound-stop
`p:sndAc/p:endSnd` action was run through the existing single-page formatter.
The output retained only advTm. This is a **confirmed existing preservation
limitation**, not a passing Apply-to-All case. The source, actual existing
single-page output, original/output transition XML and hashes are retained in
`/tmp/pr190-pptx-apply-all-limitation-evidence/evidence.json` and adjacent PPTX
files. The new inspect flag is false for this file; the new batch button and
handler refuse it without changing the original draft or bytes.

Review also found that merely counting transition containers misses an MC
AlternateContent containing only one Choice/transition. The final gate rejects
any AlternateContent in the relevant suffix, regardless of prefix or container
count. Its real-file negative passed separately. Parsing ambiguity/errors and
unparsed transition markup fail closed for this capability, without changing
single-page writeback. A new safe sample browser rerun passed with the safety
flag and unchanged [2000,1000,3000] per-page advance times.


Root integration additionally ran the single-Choice AlternateContent refusal and
the pinned-default effect control using the final production-packed bridge in
Node22, read-only, network-none container: 2 passed (5.12s). This is the explicit
mounted-runtime boundary, not a complete application image or desktop proof.
