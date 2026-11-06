# Native PDF crop all surviving pages

2026-11-06. Follow-up to `NATIVE_PDF_CROP_ACCEPTANCE.md`. This connects the
source crop-all option, not a new PDF serializer or the remaining Page commands.

## Source and operation semantics

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`, App.tsx Git blob
`e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`: lines 6697–6707 skip a full-frame
selection and apply displayed fractions to all current visible pages when
cropAllPages is set; lines 11887–11903 expose the checkbox in CropDialog.

The native crop dialog now has “裁切全部保留页”, initially unchecked and showing
the target count. Every page uses its own current CropBox and displayed rotation,
including earlier pending crops/rotations. PDF.js handles its UserUnit and inverse
coordinate transform. The active page's absolute rectangle is never copied to
other pages. Deleted pages are excluded; reordered original identities remain
unchanged. The original current-page path remains available.

`cropAllPdfPages` snapshots operations and margin inputs before asynchronous
viewport loading. It prepares every surviving target locally, validating each
rectangle and the complete 500-record budget. Only successful preparation and
an unchanged editable session can commit one NativeDraft history snapshot.
Later-page load/size errors, budget overflow, cancellation, disposal or changed
draft state cannot commit part of the batch. The dialog fields and crop opener
are disabled while calculating; forced reopening is guarded as well. Full-frame
bulk selection does not add crop operations or a history step.

The backend protocol remains existing strict `cropPage` records. No backend,
vendor, schema, signing or publication code changed. The accepted production
runtime CLI remains SHA256
`21fef59085d8081a6380606c4db2fd61dadf779e5ce4d731181e8d093107f393`.
Earlier individual-file, ASGI and Node22 proofs are retained in the preceding
record; they are not counted as new backend checks in this follow-up.

## Verification

Ten new frontend cases pass across focused selections, alongside all 18 existing
crop checks. Coverage includes mixed sizes/directions/offsets, previous crops,
rotation/deletion/reordering, late load and tiny-page failures, exact budget and
overflow, no-op at the budget, one Undo/Redo/reload step, preview invalidation,
async input snapshots, invalid restored order and malformed margins.
One initial target comparison used exact floating-point equality; it was changed
to an eight-decimal tolerance against independent expected coordinates, and only
the affected case was rerun. Repeated cases are not summed as new coverage.

`frontend/smoke/pdf-crop-all-smoke.mjs` uses production static assets and the
existing actual packed PDF engine, with substituted authorization/revision routes.
The fixture has four source pages with differing sizes, offsets, rotation and
UserUnit (1/2/3), forms and a note. It stages an earlier crop, rotates another
page, deletes one, reverses survivors and applies 10/20/30/10 percent margins.
The batch must reference source IDs 3/1/0, and width/height must shrink to 60%/70%
for every surviving page despite their differing dimensions.

The scenario verifies modal cancel/no-op/errors, cancellation during async
preparation with forced reopen, one-step Undo/Redo, real reload, three form
updates, save revision2, download despite validation failure, readonly forced
click refusal and reopen. pypdf independently checks unchanged MediaBoxes,
content streams and UserUnit, retained note, contact=Ada/consent=/Off/plan=/pro:

| Source index in output order | CropBox | Rotation | Display size |
| --- | --- | --- | --- |
| 3 | [29,111,197,303] | 270 | 576 × 504 |
| 1 | [124,112,352,434] | 180 | 228 × 322 |
| 0 | [82.2,66,287.4,388] | 0 | 410.4 × 644 |

Crop still hides content without removing it; the dialog retains the explicit
warning against using crop to remove sensitive information.

An initial browser run passed. Extending the cancellation scenario exposed a
smoke snapshot taken before asynchronous rendering finished; the smoke now waits
for the final fieldset idle state. Review also added a guard against reopening
while canceled preparation is still pending. Earlier logs are retained.
The final cancellation/reopen guard scenario and complete browser/file flow pass;
console/page errors are empty. Final source SHA256:
`03398f79925192facd4615579bdba28b4f513f623a4417f286e182448194739f`.
Final download SHA256:
`178d3720c034d298bffab8ac9a734fac824ea1bc25b1090360082e8b7f14856c`.
Accepted source/download/receipt are in
`/tmp/pr190-pdf-crop-all-browser-evidence-accepted`.

Final standard/Slides builds pass (31.29s/32.46s), including strict frontend
TypeScript. Actual bundle budget, budget contract, smoke syntax and diff checks
pass, with existing third-party chunk warnings retained. No engine changes or
new standalone bridge tsc result are claimed. Logs retain the first passing
browser, intermediate smoke timing failure and final accepted run.

## Evidence boundaries

No full frontend/repository suite, new HTTP/SQL/Node22 scenario, full application
image, deployed authorization or desktop certification is claimed by this UI
follow-up. The backend runtime is unchanged. Browser/file evidence uses actual
bytes, not a model-only preview. Feature flags stay off.

Image crop drag handles, Page Size, extract/insert/replace, split/merge, Form
Design and remaining source command/context parity remain open; Tasks 2–6 are
still incomplete. Archive: `/workspace/scratch/pr190-pdf-crop-all-evidence.zip`.
