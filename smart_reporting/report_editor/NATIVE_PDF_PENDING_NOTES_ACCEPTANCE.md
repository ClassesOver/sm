# Native PDF pending sticky-note editing/deletion acceptance

2026-11-06. Newly placed, unsaved sticky notes can now be edited or removed before
saving. This closes the pending-note mutation gap in the saved-note checkpoint;
threaded replies, full sidebar/popups and whole PDF parity remain incomplete.

## Primary source and native adaptation

Fixed GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, lines6394–6445:
  pending notes use setNoteContents rather than a saved-note edit; deleting pending
  notes drops their drawing records, with a reversible history step.
- `apps/pdf/src/renderer/edit-ops/ops.ts`, blob
  `4c5fb9c8f4f0fb0117d3a64368cd2fb546ee758a`, lines210–238:
  removeDrawing filters exactly one local identity, setNoteContents replaces only
  that note's contents and preserves the rest of the drawing input.
- Registry blob `c3f246a21eec7af95982b176b5f94761d07e1af9` documents pure reducers
  against complete edit snapshots; App applies them through the shared history.

Native drafts retain the existing addTextAnnotation save payload. Editing changes
only that record's trimmed text; deletion removes that record, not a source PDF
annotation. Coordinates, optional color/source binding, operation order and other
operations are preserved. No backend operation, vendor writer, runtime binary or
feature flag changed. The existing per-page comments area gains a separate open
“待保存便签” section; the Apply/Cancel modal is shared with saved notes.

Native pending records have no durable local annotation ID. Their UI reference
therefore binds both operation index and the exact complete serialized draft
snapshot. Any intervening edit/delete/reorder invalidates that reference. Comparing
only coordinates/text or the target record is insufficient: an identical note
can shift into a stale index. After rerender/reload the reference is recomputed
from current state. All controls share one serialized snapshot per render, avoiding
per-note serialization of potentially large drafts. This is a deliberate native adaptation, not a claim that an
index is a persistent source identity or authorization token.

Frontend validation now checks restored addTextAnnotation records against the
existing strict server contract: kind/keys, immutable source page and optional
source digest, finite rectangle/current CropBox and fixed20×18 icon anchoring,
trimmed nonempty text/max10000 and optional RGB. Malformed, deleted-page or stale
records fail before committing a new draft. Editing/deleting works at the500-record
limit without appending another operation. Undo/redo/reload use whole NativeDraft
snapshots; deleting a page removes its pending notes and undo restores them.
Readonly/save/print/preview/closed guards apply to controls and forced callbacks.

## Verification and boundaries

- 13 new frontend cases plus38 affected page/markup/saved-note cases pass: exact
  chosen record and preserved properties, identical-note stale-index rejection,
  source binding under reverse/delete, full history/reload, operation budget and
  malformed restored payloads. No full suite was rerun. Initial production typing
  found only test-array union inference issues; annotating the test fixtures fixed
  that without changing tested runtime behavior. Raw failed build logs are retained.
- New production-static Chromium154.0.8037.57 case places two genuinely identical
  notes through pointer events on UserUnit2/offset CropBox at50% zoom, deletes one,
  then dispatches its detached old button: stale mutation is refused and the second
  note survives. It verifies modal cancel, Unicode editing, deletion, undo/redo,
  reload, readonly controls and forced mutation refusal, rotated-page placement,
  deletion/undo of a page containing a pending note, reverse plus unrelated-page
  deletion, actual save/download and revision2 reopen as saved notes. The final
  payload contains only the existing addition/page operations, not saved-note edits.
- The affected saved-note Chromium scenario also passes through the shared modal:
  cancel/source restore, edit/delete, history/reload, actual preview and revision2/3
  save/download/reopen. This is one affected scenario, not new source functionality.
- Independent pypdf reads the new actual download: output pages are original1,0;
  raw content streams/text, boxes, rotation/UserUnit and form values are unchanged.
  Original note dictionary is unchanged, both new contents/rectangles and AP streams
  are verified, deleted pending text is absent. Pending notes become three total
  saved notes (including the original) and no pending records on reopen.
- Final Standard41.45s/Slides36.63s builds include strict frontend typing; actual
  budgets, smoke syntax and diff pass. Backend/service/package source is unchanged;
  existing runtime CLI SHA remains
  `985d30ccc45d8f1ef234d7f717d0c02be7ee9951faa0372f0da111780758f748`.
  No old backend/Node22/SQL results are counted as new checks.

New source SHA256:
`f1178479e91cb36db0c7c6305b0e8bf1c406510448344c698bce2483d0ee1c76`.
Actual downloaded SHA256:
`161fb90e1b890bcacc7f9658c3cff3f225cb09006930ef053f10f86d0053bc7a`.
Evidence: `/workspace/scratch/pr190-pdf-pending-notes-evidence.zip`, with primary
sources, focused logs, both browser scenarios, actual PDFs/screenshot and
independent readback.

Auth/revision routes are substitutes; actual PDF.js, packed engine and download
bytes execute. This does not prove production authorization/SQL, full application
image or desktop compatibility. Pending-only “校验当前修改” keeps its existing
validation-summary behavior; this slice does not add an actual-output preview for
that path. New-note creation timestamps still come from the existing writer at
save time; no byte-identical pending-note preview claim is made. That preview/time
binding gap is tracked explicitly, separately from the saved-note deterministic
edit protocol. Replies/threads/full context remain open. Flags stay off.
