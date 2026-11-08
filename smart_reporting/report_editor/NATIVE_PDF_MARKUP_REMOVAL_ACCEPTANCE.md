# Native PDF saved-markup removal acceptance

2026-11-06. Supersedes the saved-markup-removal gap in the earlier selected-text
checkpoint, for safely readable ordinary Highlight/Underline/Squiggly/StrikeOut
annotations only. Whole-PDF parity remains incomplete; flags remain off.

## Primary source and adaptation

Fixed GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, lines2790–2855:
  match pending first, then one saved annotation with equivalent quads, excluding
  pending deletes. A fully marked selection removes its matches; a partial one
  marks only the unmarked pages. The selection survives toggles.
- Original save-pdf.ts blob `4713ad820f4854479cdf73a9586051631f79de73`,
  lines1583–1587: annotation deletion precedes text/image rewrites.
- Original annot-delete.ts blob `660951ad1e2556276245f64054af23fd4929e081`:
  object-number lookup with geometry fallback and fail-soft missing matches.

The native adapter deliberately uses a stricter contract: source digest, original
page ID, annotation ordinal-derived ID and exact dictionary SHA256. It unlinks
only that original page's Annots slot with pdf-lib before the unchanged pinned
writer runs. It copies the array because multiple pages may share an indirect
Annots array. It neither broadens vendor annotDeletes nor uses approximate
geometry as a deletion identity. Source/vendor files and licenses are unchanged;
bridge adapter provenance and local hashes are recorded separately.

Inspect exposes per-mark identity, removable and reason. Signed fields, catalog
Perms, XFA, incomplete reference census, direct annotation dictionaries, replies,
popups and structure-linked annotations remain readonly. Other annotation types,
widgets, existing comments and their replies are not removal targets. All operation
identities/conflicts are validated before writing; stale/forged/duplicate requests
refuse without returning partial output. Removal may compose with add, crop,
rotation, delete/reorder of other pages, supported form/size operations and supported
text replacement. Page-size/crop/text preexisting combination limits still apply.

Home/Annotate toggles stage one complete draft snapshot. Pending additions take
precedence over coincident saved marks, matching source behavior. Undo/redo/reload,
partial selection skips, operation budgets and old-engine capability refusal are
preserved. Red dashed outlines indicate pending removal over the original canvas;
“校验当前修改” displays the actual output PDF. No white cover is used. Removing
an annotation does not securely erase orphan objects and is not redaction.

## Verification and its limits

- 18 new file cases across focused runs: all four subtypes; unchanged raw page
  streams/text/boxes, forms, note and surviving AP; duplicate geometry with unique
  identities; revision binding; forged IDs/hashes/source/extra geometry fields;
  duplicate and late-invalid batches; five readonly structures; shared arrays;
  rotation/reorder/other-page deletion/size; actual text replacement composition.
- Three new frontend checks plus31 affected markup/page checks pass. New service
  case and prior add-markup service case pass: independent text flag, actual
  preview receipt, changed-identity refusal, save/download equality and retained
  artifact despite business validation warning. Two affected malformed-source/
  reorder-markup cases pass. No complete suite was rerun.
- Production-static Chromium154.0.8037.57 exercises real multiline DOM Range,
  four source types, colors, history/reload, deletion/reversal, real preview and
  download/reopen revision2; then saved underline removal, identity, two outlines,
  undo/redo/reload, actual preview, revision3 download and reopen. Independent
  pypdf verifies every content stream/text and box, remaining appearance streams
  (including form appearance states), and form values. Routes substitute auth/
  revision persistence; service tests exercise the actual service separately.
- Standard build37.11s, Slides build32.11s and both actual budget checks pass.
  Standalone bridge typing retains the same six baseline desktop declaration
  diagnostics, zero new; it is not a clean standalone typecheck. Local manifest
  verifies33 items. Runtime CLI SHA256:
  `5b65307962fad57690807bf8afcefced3e9aad54f6a99393e192dd305c9e9823`.
- Node22-slim readonly/network-none mounted runtime verifies actual removal,
  removal surviving a font-unavailable text skip, and forged identity refusal
  without an output file. This container has no host fonts: the initial combined
  text assertion failed because text was explicitly skipped; that failure is
  retained. Host file tests separately prove actual replacement composition.
  This does not close full application-image/font/desktop/deployed acceptance.

Browser fixture source SHA256:
`4d32feecf6fb853aed8f76a9cd7bbae34c9c5b08bfc357602bd3f24bc7ad8890`.
Revision2 SHA256:
`192f385fadf64e23bd0cda9ec4e859f2d1fd952dae6ecc70d7cb617e47dcafe6`.
Removal revision3 SHA256:
`0855e04cacd7ff7e121c8e81f03501b0148e7a7975cbffb9c187f623a42e9c4f`.

Evidence: `/workspace/scratch/pr190-pdf-markup-removal-evidence.zip`, including
original materials, raw failed iterations, accepted focused logs, PDFs, screenshot,
independent readback and container receipts. Initial implementation lost source
markups through an undefined ordinal in a fail-closed inspect catch; fixed before
accepted tests. Test-only fixes compare indirect references by object identity
rather than Python reader memory addresses, create a separate immutable service
source path, and inspect stateful widget AP dictionaries correctly. Earlier failed
runs are not counted as passes or new checks.

Remaining: linked/complex source removal, arbitrary annotations/editing/replies,
full contextual behavior, desktop visual verification, full image build, production
identity/network and complete PDF functionality. See `NATIVE_PDF_ALIGNMENT_STATUS.md`.
