# PDF saved flat-leaf reply edit/remove acceptance

2026-11-09; continuation of PR #196. Only safe leaves of standard flat threads
are newly mutable; root-body/subtree and complex thread behavior remain open.

## Original materials and implementation choice

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` App.tsx noteEditOps/
deleteNoteItem, CommentsPanel/note-threads and save-pdf.ts noteEdits define the
source behavior. The original annot-delete.ts was additionally fetched at that
exact ref: Git blob `660951ad1e2556276245f64054af23fd4929e081`. All five primary
files and hashes are archived. Its deletion path uses PDFium object-number hints
with rect/contents fallback; saved-note editing can silently miss unmatched targets.
These are static source findings, not a claim that this original PDFium deletion
module was executed or newly shipped.

This slice extends the existing exact native editNote/removeNote adapter instead.
No new public operation kind, upload/signing route, dependency, WASM or vendor
writer change. All21 vendor modules match the preceding HEAD;43 current LOCAL
manifest entries verify. Source SHA, page/annotation identity and full dictionary
digest remain required or source-bound as before; rect/contents never identify a
reply. UI thread matching additionally confirms the exact native parent identity.

## Mutation boundary and preservation

The shared full-source census exposes a leaf only when its root/thread is safe:
standard same-page /IRT-to-root and /RT /R, unique page membership, supported flags,
plain contents and no popup/structure/rich/state information. Global incoming
counts must prove the child has only its page-array reference and no descendants
or other aliases. Protected/signature/XFA/permission, shared, nested, cross-page,
group, locked/hidden, rich and ambiguous cases stay readonly. Root bodies with
replies stay readonly even when their leaves can be edited. The source/visit limits
and existing500-operation/12 MiB JSON/24 MiB online source ceilings remain.

Editing changes only /Contents and operation-bound UTC /M, preserving /IRT, /RT,
/CreationDate (including absence), author, geometry and AP references. Deletion
unlinks the exact page slot and releases only the proven globally unshared leaf
dictionary. Other resources and immutable source revisions may remain; this is
not secure erasure. A real unlink-only counterexample retains an unreferenced
reply dictionary whose /IRT still increases the conservative global count, making
the next thread census readonly. Releasing the safe leaf keeps the root and
surviving sibling replyable; removing the last child restores ordinary-root behavior.

After either mutation, every surviving annotation's sequence, reference and
full dictionary is read back from the saved bytes. Root and siblings must remain
unchanged apart from other explicitly requested operations. Duplicate/stale/
forged mutations fail. Leaf changes can combine with safe new saved/local replies,
notes, rotation/reorder, form values and attachments. Text replacement, crop and
page-size mixtures remain refused pending preservation proof. UI geometry/text
staging validates the complete next snapshot before committing, preserving drafts
when combinations fail. Business validation failures still retain generated downloads.

The pane provides edit/remove for exact eligible saved leaves, with draft undo/
redo/reload and actual preview/save/reopen. Parent ambiguity, duplicate references
or missing parents remove UI mutation identities. Preview/readonly/closed/saving/
printing and stale pane/modal guards apply. Capability checks cover both thread
buttons and ordinary page cards; turning off savedReplyEdits disables leaf editing
without disabling unrelated ordinary-note editing. No authenticated author/ownership
claim is added; existing document/revision authorization remains authoritative.

## Tests and independent evidence

- Five new real engine cases cover identical-looking leaves, exact edit/remove,
  creation/date/IRT preservation, deterministic bytes, stale/foreign/extra-field
  refusal, unsafe graphs, combined new replies/page/form/attachment work, future
  append after reopen, last-child removal and the unlink-only counterexample.
  Eighteen affected engine cases pass. The combined22-case run and later added
  counterexample are23 unique cases, not27 from repeated runs.
- Three new frontend cases plus33 affected checks pass,36 total. They cover exact
  leaf projection, sibling/root preservation, restored operations/history,
  source-text restoration, malformed parent graphs, preview identities and
  unsupported mixtures.
- Seven actual service cases pass (two new saved-leaf mutations plus five saved/
  local reply and attachment cases). Preview/save/download agree across timezones;
  forged/changed leaf targets fail and business validation warnings retain actual
  downloads. Fourteen selected ordinary-note/markup file cases verify widget/form,
  source protection and AP/content preservation after adding generic readback.
- Production-static Chromium154.0.8037.57 uses two saved leaves with identical
  contents, rect and dictionary digest but different source identities. It edits
  one and removes the other, checks undo/redo/reload, stale saved-reply modal
  refusal, actual preview/download and readonly reopen. Prior saved/local replies,
  root-edit/cascade, cache/fault/retry, filter/navigation and mobile checks remain.
  An explicit capability-off scenario disables saved-leaf actions in both pane
  and page card while an unrelated ordinary-note edit stays enabled.
- Independent pypdf checks the actual download: exactly one specified old reply
  changes Contents/M and the other disappears from active annotations; the root,
  preserved creation-date absence, author/IRT/RT/geometry/AP and other original
  objects remain. New saved/local replies keep their correct separate parents.
  Retained page streams/text/boxes, form values/widgets and original AP data match;
  only explicit control-note edit, additions and page deletion/order differ.
- Node22.23.4-slim, offline with readonly runtime, performs real leaf edit/remove.
  Independent pypdf verifies parent/date/form preservation; a forged leaf digest
  exits nonzero without output. This mounted runtime is not full image acceptance.

Final Standard/Slides builds, Standard budget, source identities, smoke syntax
and diff pass. Slides has no equivalent configured budget. Bridge typing retains
six existing desktop diagnostics and zero new; no whole repository suite repeated.
One independent-reader assertion was corrected to compare cross-reader object
number/generation tuples rather than pypdf object equality (which also includes
reader identity); all content/dictionary assertions remain.

Runtime SHA256:
`588bfa2805f6438aea5184d60b6cd59b50daae07effe2f51b2ba542c6612e8b2`.
Browser source SHA256: `26781ac448e2f96ede34b0d8cd9f497b9e9fb037e4aded024b4e99ace926bed5`.
Actual downloaded output SHA256: `085f6167c01b9ff8b73aad158a58119fc7d349af6852599b45bce1c706052bbb`.
Standard35.73s/Slides39.85s final builds pass.

Evidence: `/workspace/scratch/pr196-pdf-saved-reply-edits-evidence.zip`, including
primary files, counterexample, generated/actual downloaded PDFs, independent
script/results, packaged runtime and focused browser/engine/service/file/build logs.

Browser identity/revision routes and service repositories are substitutes, not
production SQL/authorization evidence. Root-body/whole-thread subtree operations,
nested/popup/rich/complex mutations, authenticated authors, full context/popovers,
other PDF families and full image/production/desktop acceptance remain open.
Flags stay off; no merge or deployment. Overall alignment remains unfinished.
