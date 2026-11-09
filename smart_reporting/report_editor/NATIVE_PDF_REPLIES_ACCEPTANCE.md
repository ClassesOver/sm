# PDF saved flat-root reply acceptance

2026-11-09; bounded continuation in PR #196, not full comment/PDF/desktop parity.

## Original materials and counterexample

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`: App.tsx replyToNote,
CommentsPanel.tsx, note-threads.ts and save-pdf.ts findNoteAnnotRef/addDrawing(note).
The full writer was fetched again through GitHub at that exact ref: Git blob
`4713ad820f4854479cdf73a9586051631f79de73`, SHA256
`21648506698c378492dffee6ab4afc7d80e75cc589e184ae1e334d1ff4fca74b`, matching the
original SOURCE manifest and archived primary file. The four primary materials
are retained, including the fresh remote writer. All21 vendor modules remain
byte-identical to the preceding HEAD, with its documented existing adaptations.
The current LOCAL manifest verifies40 entries. No dependencies or WASM change.

The source app creates flat replies at the root's position/color with /IRT pointing
to the root and /RT /R. It supports saved roots and unsaved local IDs; this native
slice implements saved roots only. The source writer matches saved parents by
rect/content with an object-number hint, and silently makes an ordinary root
note if the parent is unresolved. A real original-writer counterexample in the
archive demonstrates that orphan fallback. Another case targets the wrong one
of two identical-looking roots. Native post-write checks reject both outputs,
even when appended count, text and rectangle are otherwise correct.

## Implemented boundary

A strict replyNote operation contains immutable source page ID, root annotation
ID and dictionary digest, bounded trimmed contents and a required creation instant;
optional source SHA must match. Coordinates, parent object numbers and authors
are not accepted from the client. The backend derives the root's position/color
from the verified source. Body length is1–10,000 UTF16 units; creation time is an
integer Unix millisecond within the existing note range. Existing500-operation/
12 MiB JSON and24 MiB online source budgets remain in force.

An iterative reference census is bounded to20,000 indirect objects and200,000
visited items. It allows an indirect saved Text root and standard same-page flat
RT/R children. Exact page membership, parent links, reference counts, normal
contents/geometry/color and supported flags are required. Only Print/NoZoom/
NoRotate flag combinations are accepted. Signature/ByteRange, signature fields,
XFA/permissions, shared references/arrays, popup/structure/rich/state information,
nested/group/cross-page/ambiguous threads and locked/hidden/unknown flags remain
readonly. Reply capability is separate from body edit/remove: a safe root with
existing replies can accept another reply while its original body stays readonly.

Reply writing runs after supported page/form/note/attachment stages. The exact
parent reference and dictionary must still match the source before the pinned
writer runs. Afterwards append counts/payload, exact /IRT and /RT /R, canonical
UTC dates and every pre-existing annotation reference/dictionary are verified.
The preview digest includes actual final bytes. Root edit/remove in the same
batch, parent-page deletion and text replacement/crop/page-size mixtures fail
before any output file is created. UI page deletion deliberately drops that
page's pending operations as before, with undo restoring the full snapshot.

The whole-document pane offers replies only for exact native root identities.
Reply drafts can be edited/canceled and undo/redone, restored after reload and
viewed in actual output preview. Editing preserves the original creation instant.
Pending replies disable root-body editing. Document/draft/generation guards reject
old pane controls and obsolete modal callbacks; readonly, preview, printing,
saving/closed and engine capability are respected. Author uses the existing
writer default; no authenticated-person identity or author integration is claimed.
Pending reply navigation can fall back to its page; a new reply-specific page card
and full source popover behavior are outside this slice.

## Verification and independent witnesses

- Five new real engine cases cover duplicate-looking roots, repeated flat replies,
  exact parent references, deterministic receipts, stale/foreign identities,
  schema/mutation/geometry conflicts, protected/complex/shared/locked/hidden
  sources, rotation/reorder/form combinations and both original-writer parent
  counterexamples. Nine affected engine cases pass (seven attachment and two
  appended-note/date guards). Reruns are not counted as new cases.
- Two new frontend cases plus28 affected cases pass,30 total. They cover exact
  root validation/projection, restored records, pending reply edit/cancel with
  immutable time, stale snapshot refusal and deliberate page-deletion behavior.
- Eight selected real service cases pass: two new reply/timezone variants plus
  six existing note/markup/attachment cases. Actual preview/save/download agree
  across UTC/Tokyo/Los Angeles; changed payloads and forged digests fail. Source
  bytes remain unchanged and business validation warnings retain saved downloads.
- Production-static Chromium154.0.8037.57 checks thread/author filters, exact cache
  and fault/retry counts, existing safe note editing, pending reply add/edit/cancel,
  undo/redo, reload, stale closed-pane button and stale open-modal refusal. It
  combines explicit note edits/addition, page reversal/deletion and a reply to a
  surviving saved thread, then actual preview/return, save/download and readonly
  reopen/mobile close. Original assertions remain; test selectors were corrected
  to activate the View tab and reapply the filter that pane close deliberately clears.
- Independent pypdf verifies the real downloaded reply and original reply have the
  same exact root reference, /RT /R and expected contents. Original annotation
  dictionaries/AP, retained page streams/text/geometry and form values remain;
  only the requested control-note edit, new note, page deletion/order and reply
  occur. A separate fixture proves the second identical-looking root is selected.
- Node22.23.4-slim, network disabled and runtime readonly, writes a real reply.
  Independent pypdf checks parent and UTC date; forged root digest produces a
  nonzero exit and no output file. This mounted runtime is not a full app image.

Final Standard/Slides builds, configured Standard budget, source manifests,
smoke syntax and diff checks pass. Slides has no equivalent configured budget.
Standalone bridge typing remains6 existing desktop declaration diagnostics with
zero new. Initial type checking caught a duplicated invalid-page branch and an
incomplete test fixture; both were corrected. No whole repository suite repeated.
Browser authorization/revision routes are substitutes and service repositories
are controlled fixtures, not production SQL/authorization acceptance.

Runtime SHA256: `d738ba087903ee67991f014b31876333ebeb4c8eb7f74a4712486cc7c6d17b56`.
Final browser source SHA256: `b4850a592dd7c1d3715c6ecb53a48ea6aafa0eb772dd2fb2a41058a8fb7b1660`.
Actual downloaded output SHA256: `b5b5d1dd2b9d153ec3bd977f841ace1973ca634099addd7568185df5b11c0cc8`.
Standard/Slides final parallel builds report1m9s/1m11s respectively.

Evidence: `/workspace/scratch/pr196-pdf-replies-evidence.zip`, including primary
sources, original-writer counterexample, actual files, independent script/results,
packed runtime, offline witness and focused test/build records.

Pending-root/local-ID replies, nested/popup/rich/complex threads, saved-reply
edit/delete, authenticated authors, full source context/popovers and the other
PDF/desktop/full-image/production gaps remain open. Flags stay off; no merge or
deployment is claimed. This supersedes the previous wholly missing reply-write
gap only; the overall plan remains unfinished.
