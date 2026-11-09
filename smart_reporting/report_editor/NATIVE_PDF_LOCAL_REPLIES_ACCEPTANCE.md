# PDF pending-root reply identity and lifecycle acceptance

2026-11-09; bounded continuation of PR #196 after saved-root replies. This closes
pending-root flat replies, not all PDF comment or desktop behavior.

The later bounded saved-leaf edit/remove implementation supersedes this
checkpoint's wholly missing saved-reply mutation gap; see
`NATIVE_PDF_SAVED_REPLY_EDITS_ACCEPTANCE.md`.

## Primary materials and method

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`: App.tsx replyToNote,
CommentsPanel.tsx, note-threads.ts and save-pdf.ts addDrawing(note). Full primary
files are archived, including the writer previously fetched at this exact ref:
Git blob `4713ad820f4854479cdf73a9586051631f79de73`, original SHA256
`21648506698c378492dffee6ab4afc7d80e75cc589e184ae1e334d1ff4fca74b`.
All21 vendor modules remain identical to the preceding HEAD;42 current LOCAL
manifest entries verify. No dependency/WASM/vendor writer change.

The source passes a localId for an unsaved root and replyToLocalId for its replies.
The native implementation uses that unchanged writer branch, with a strict graph
at the public boundary. It defers referenced roots from ordinary drawing work,
then writes all roots before replies, after supported page/form/note/attachment
changes. Input operation order does not become a parent lookup heuristic.
Actual PDF references are checked after writing; matching text/coordinates is
never a substitute for identity. A real original-writer missing-local-parent
fallback produces an ordinary note; post-write validation rejects that output.
Another counterexample reuses an old root reference with otherwise correct
appended count/text/geometry; the fresh-reference check refuses it.

## Contract and lifecycle

- addTextAnnotation accepts an optional32-hex localId. replyPendingNote requires
  source pageId, parentLocalId, trimmed1–10,000-character contents and a bounded
  integer creation instant; optional source SHA must match. Extra fields, duplicate
  root IDs, absent/foreign/cross-page parents and local IDs on child operations fail.
  Parent targets are root addTextAnnotation operations only; nested replies are
  outside this protocol. Existing500-operation/12 MiB JSON/24 MiB online source
  limits remain. Signature/XFA/permission and unreadable/over-budget reference
  sources advertise pendingNoteReplies=false and cannot write this graph.
- The first reply to a legacy draft root assigns its identity and adds the reply
  in one NativeDraft history transaction. Already identified roots retain it.
  Each operation is cloned independently: even callers reusing one JavaScript
  object for two value-identical roots cannot accidentally identify both.
- Editing a pending root preserves identity and children. Deleting it removes its
  replies atomically; undo restores the complete prior graph. Canceling replies
  keeps the root identity. Pending reply edits retain their original creation
  instant, and scoped draft reload preserves the graph. Unknown legacy root
  creation times remain unknown; no timestamp is invented.
- Existing reply modal, pane/document/draft/generation guards, actual preview,
  immutable publication and readonly reopen apply to both reply kinds. IDs are
  draft-only and never written as PDF metadata or treated as saved object IDs.
- Referenced roots and children use new unique PDF references, distinct from old
  annotations. Root notes cannot already be replies. Output append counts,
  subtype/text/rectangle, exact /IRT and /RT /R, same-page parent and UTC dates are
  verified; every old annotation reference/dictionary remains unchanged. The
  fresh-reference restriction applies to this local graph, preserving the prior
  ordinary-note/text-transform checks. Saved and pending root replies coexist.
- Parent-page deletion in raw operations, text replacement, crop or page-size
  mixtures remain refused. UI page deletion deliberately drops that page's
  pending operations with undo, as before. Rotation/reorder, unrelated notes,
  form values and attachment changes have real compound-file evidence.

## Verification and independent witnesses

Four new engine cases cover identical-looking roots with forward input references,
unknown dates and deterministic output; duplicate/orphan/cross-page/protected and
unsupported graph refusal; multiple roots/children with rotation/reorder/note/
form/attachment changes; and reused-reference/missing-parent/orphan counterexamples.
Fourteen affected engine cases also pass (saved replies, appended-note/date guards
and attachments). New tests run without a pre-existing evidence directory; fixture
export is optional via PDF_LOCAL_REPLY_EVIDENCE_DIR. Reruns are not extra cases.

Three new frontend cases plus30 affected cases pass,33 total. They verify atomic
legacy migration, identity reuse, identical-object alias separation, exact thread
projection, root edits and cascade removal, history/storage restoration, preserved
reply times and stale/invalid graph refusal. Strict bridge typing retains6 existing
desktop declaration diagnostics and zero new. The first check caught an imprecise
root filter type; it was narrowed explicitly. A test also exposed structuredClone
preserving aliases across reused input objects; per-operation cloning fixed it.

Five real service cases pass: two new local-root/timezone variants, two saved-root
reply variants and the existing attachment case. Actual preview and downloaded
save bytes agree across Tokyo/Los Angeles, changed/forged parents fail, and failed
business validation still yields a readable saved download. These are controlled
service repositories, not production authorization/SQL acceptance.

Production-static Chromium154.0.8037.57 exercises first reply, editing its text,
editing the root without losing children, root-delete cascade, undo/redo and full
reload. It retains saved-root replies and old cache/fault/retry, filter/navigation,
stale pane/modal, actual preview/return, save/download and readonly/mobile checks.
No previous assertion is relaxed. The final graph contains one local-root reply
and one new saved-root reply, alongside the original saved reply.

Independent pypdf verifies the actual downloaded file: local child /IRT points to
the edited new root; original and new saved replies retain the other exact root.
Root/child IDs are distinct, local draft identity is not stored in /NM, original
retained page streams/text/geometry, forms and original annotation/AP dictionaries
remain, and only explicit note edits/additions, reply additions and page order/
deletion occur. A separate engine fixture proves the second identical-looking
root is selected while its unknown creation date remains absent.

Node22.23.4-slim, network disabled and runtime mounted readonly, writes a real local
root/reply graph. Independent pypdf confirms exact parent/UTC child date and no
invented root date. A forged local parent exits nonzero without creating output.
This is a mounted-runtime check, not full application-image acceptance.

Standard43.36s/Slides37.13s builds, configured Standard budget, source identities,
smoke syntax and diff checks pass. Slides has no equivalent configured budget.
No whole repository suite was repeated. Browser identity/revision routes remain
substitutes. Runtime SHA256:
`bf786ce3e52ba15530d742e13bb0e3f8160188e9219d49e8babced951c0caa6f`.
Browser source SHA256: `596233fcfabfad52902c3805f3c51aed652d64ef9889bb84862c1a4b2896b344`.
Actual downloaded output SHA256: `8d467107a7fc98495e4c0a23b525997db5d726e69f666aba508113c67a31dedc`.

Evidence: `/workspace/scratch/pr196-pdf-local-replies-evidence.zip`, with primary
sources, actual files, independent script/results, packed runtime and focused
engine/frontend/service/browser/offline/build records.

Nested/popup/rich/complex threads, saved-reply edit/delete, authenticated author
integration, reply-specific page cards/full context/popovers and other PDF/
desktop/full-image/production gaps remain open. Flags stay off; no merge or
deployment. The overall plan remains unfinished.
