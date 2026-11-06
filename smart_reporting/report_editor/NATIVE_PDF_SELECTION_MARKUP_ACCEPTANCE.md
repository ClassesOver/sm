# Native PDF selected-text markup acceptance

**Follow-up:** bounded saved removal is now accepted in
`NATIVE_PDF_MARKUP_REMOVAL_ACCEPTANCE.md`. Statements below describe the original
addition checkpoint and its then-current refusal behavior.

2026-11-06. Connects fixed-source Highlight/Underline/Squiggly/StrikeOut additions
and pending-markup toggles. Saved-markup removal remains explicitly unavailable;
this is not complete Markup or whole-PDF parity. See `NATIVE_PDF_ALIGNMENT_STATUS.md`.

## Original material and native adaptation

Pinned source `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, lines2813–2857:
  selected text is grouped by original page; fully marked selections toggle off,
  partially marked selections skip existing matches rather than duplicate them.
- Renderer annotations.ts blob `23f271129e0723f1a652f2d68da4cbd3d532d2bb`:
  selectionQuadsByPage drops enclosing/duplicate DOM boxes, normalizes lines and
  maps through rotation/CropBox/UserUnit; quadSetsMatch uses source tolerance2.
- Unmodified Node `src/main/save-pdf.ts:131–251` creates actual annotation
  subtypes, QuadPoints, colors and AP streams using final page rotation.

The renderer helper is reused in `genoffice-pdf-annotations.ts`. The adjacent
source manifest records original/current SHA256 and only three adaptations:
local type import, native content-box selector excluding headings/borders, and
a provenance/change notice. The upstream geometry/matching algorithm is retained.
GenOffice LICENSE/NOTICE remain preserved. No new PDF/AP writer was invented.

Home and Annotate controls now capture real text selection rather than routing
these source commands into a generic rectangle tool. Selection snapshots survive
native redraws so additional types can stack and pending additions can toggle.
Structural edits clear that scope. Four source colors are retained:
highlight=[1,.87,.35], underline=[.17,.4,1], squiggly=[.13,.65,.35],
strikeout=[.86,.22,.18]. Only highlight accepts the existing custom palette.
Pending overlays indicate intent; actual PDF preview renders the pinned AP bytes.

The strict `addMarkup` record binds pageId/source digest and contains markupType,
canonical unrotated quads and RGB. Each page accepts1–200 finite nondegenerate
quads, within its current CropBox; the shared500-record budget remains. Source
metadata exposes readable saved markups and per-page markupReadSafe. Missing
engine capability or unreadable source markup disables these controls; forced
requests repeat the boundary. Legacy rectangle-highlight API/drafts remain
supported and exact single-quad pending matches toggle instead of duplicating.

Every selected target is prepared/validated before one NativeDraft commit.
Malformed stored records, out-of-bounds/deleted targets, bad color, budget or
quad count errors retain the previous draft. Existing saved matches are skipped
when adding a partially marked selection. A fully marked saved selection is
pressed/disabled with an explicit unsupported-removal reason; forced UI dispatch
also refuses. No annotation-delete fallback, fabricated identity or duplicate
addition is presented as saved-markup removal.

## Verification

**44 distinct new file cases** pass in `test_pdf_selection_markup.py`:
32 combinations of four types, four rotations and UserUnit1/2 check real subtype,
16 QuadPoints for two lines, RGB, AP stream presence/style, unchanged source
content/text/CropBox/rotation/units/forms and stale identity refusal. Ten bad
record cases, unreadable source-markup gate and reorder/delete/rotation source
composition complete the set. **40 affected existing bridge/crop file checks**
also pass, along with **four affected size/text-service checks**.

**14 distinct new frontend cases** pass across focused runs, plus52 affected
crop/batch/paper/operation checks. Coverage includes pending toggle/stack behavior,
partial saved matches, unsupported saved removal, no selection, budget, legacy
pending highlights, pinned matching/rotation/UserUnit mapping, complete-selection
validation and malformed/out-of-bounds/deleted stored operations. The initial
manual UserUnit expectations were wrong; independent arithmetic corrected that
fixture and only its affected case was rerun. No source transform was patched to
fit the test. Repeats are not added as new cases.

One new native service case verifies markup preview/digest, changed-color digest
refusal, actual revision2 save/download and source text preservation while the
independent text-edit feature is off. Validation failure retains the actual
artifact/download. It uses synthetic scope and memory repositories, not deployed
HTTP/SQL/tenant identity proof. The existing publication/signing code is unchanged.

Final packed Node22 readonly/network-none runtime: **2 passed,42 deselected**,
covering rotated/UserUnit2 squiggly and source reorder/rotation composition.
Runtime CLI SHA256:
`617bb24d1e4bb2ba67b01a615a9e8ef00bdd11f798bcb15946ad400827a5d4ec`.
This is mounted-runtime evidence, not a complete app image.

## Browser/file proof

`frontend/smoke/pdf-selection-markup-smoke.mjs` runs production static assets in
Chromium154 with the actual packed engine. Authorization/revision routes are
substitutes. Its real DOM Range covers two visible text lines on a UserUnit2 page
with an offset CropBox; the pinned helper excludes clipped/off-page text.

It verifies no-selection disable state, two-line underline addition/toggle,
custom blue highlight, source-colored squiggly/strikeout, Undo/Redo and genuine
reload; then deletes another source page, reverses survivors, loads actual output
preview, saves revision2, downloads and reopens. Independent pypdf checks four
real annotation subtypes,16 coordinates per annotation, source-space line origins
near x25/x30 and baselines450/420, expected RGB, AP streams, unchanged content/text
and form values. Existing-source markings are recognized on reopen; their
unsupported removal is disabled and a forced click retains an empty draft.

Final Chromium version: 154.0.8037.57. Accepted source SHA256:
`ee9f217099e16f9f08b60bea2d0df0ab63d233c18c7e7bfd22b2997bddda8822`; output SHA256:
`31086d295c6505f9eb14b33c87f179bd2a7ab42aac312af71a911685386dd4ae`. Both actual preview canvases/text layers complete,
with displayed sizes380×460 and760×920. Accepted bytes and receipt are retained
in `/tmp/pr190-pdf-markup-browser-evidence-closed`.
Final standard/Slides builds pass (32.18s/32.60s), including strict frontend types;
actual budget and budget contract pass, along with Ruff/smoke syntax/diff checks.
The subsequent source change notice is comment-only; source hashes are rechecked. The initial browser passed; an intermediate rerun
waited on an obsolete localized help string after that text was corrected. The
smoke now waits on actual editable control readiness; it does not suppress browser
errors or bypass guards. Earlier logs are retained.

## Provenance and limits

All32 engine local SHA entries and original/adapted renderer SHA records are
checked. Only bridge/operations.ts changes inside that engine manifest; vendored
Node writer and upstream SOURCE hashes are unchanged. Standalone bridge strict
check has zero new diagnostics and retains six existing desktop type-only/
Electron diagnostics, not a clean tsc pass. Full frontend strict typing is part
of both production builds. No full repository/frontend suite was repeated.

Evidence archive: `/workspace/scratch/pr190-pdf-selection-markup-evidence.zip`.
Remaining: saved annotation editing/deletion, full context/popover behavior,
noncanonical/unsupported source markups, arbitrary transformed text, desktop and
production/SQL/full-image acceptance. The overall PDF matrix lists other Page,
Form Design, conversion and external-service gaps. Flags stay off.
