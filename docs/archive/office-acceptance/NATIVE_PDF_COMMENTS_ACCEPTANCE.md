# PDF whole-document sticky-note sidebar acceptance

2026-11-09. This closes bounded read/navigation support, not whole-PDF parity.

## Primary source and implementation

Pinned GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`:
`apps/pdf/src/renderer/note-threads.ts`, `CommentsPanel.tsx` and App.tsx
(blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, document annotation loop,
View navigation and panel wiring). Original note-thread/panel files are retained
in the evidence archive. `genoffice-pdf-comments-source.json` records original
SHA256 and the unchanged extracted date parser's local SHA256.

The enabled View comments control opens an all-surviving-page Text-note sidebar.
Thumbnails, outline and comments are mutually exclusive, as requested. Search
matches body/author across roots and replies; sorting uses current display page,
root creation/modification time, with unknown times last. Closing resets the
filter. Replies are collapsible and readonly. Hidden/group replies follow source
exclusions; orphan, cyclic and duplicate relationships retain visible readonly
items rather than silently dropping them. Iterative graph/filter traversal handles
12,000-deep chains without recursive overflow.

Clicking a row navigates by immutable original page identity and opens/focuses the
existing saved/pending note card; editing/deletion reuse its existing controls and
history. The inspect-only optional `sourceRef` preserves object number and generation
(`80R3`, generation zero `80R`, direct dictionary null). It matches PDF.js references
exactly; it is never a write identifier. Writes still require original annotation ID
and dictionary digest. Unmatched references navigate to the page with a warning.
Linked/reply, complex/protected and ambiguous source mutations remain refused.
At this read checkpoint there was no reply creation/edit/delete protocol.
The later bounded saved-root creation protocol supersedes that part only; see
`NATIVE_PDF_REPLIES_ACCEPTANCE.md`.

A document-keyed promise cache shares inflight reads and successful page reads;
failed/malformed pages are evicted for retry. Partial failures show unread page
counts, not a false empty result, while pending notes remain visible. Projection
uses immutable source note metadata plus current draft operations. Source and
actual-preview PDF.js documents have distinct caches; actual preview rows navigate
readonly output cards. Generation/document/draft guards reject obsolete callbacks
and cancel abandoned lists. Refresh/document switches immediately clear old rows;
a delayed-preview browser check verifies no stale-source list flashes.

## Evidence and checks

- Seven new frontend cases cover exact full-generation identity, pending edit/delete
  projection, unchanged raw input, malformed/orphan/cyclic/duplicate threads,
  reply/author filtering, ordering, preview ordinal mapping, 12,000-depth traversal
  and cache concurrency/retry/document separation. Twenty-five affected View/saved/
  pending-note checks pass across selected runs; repeated selections are not counted
  again. One new bridge case checks nonzero generation, direct-note readonly and
  rejects `sourceRef` as extra write metadata.
- Twelve existing affected file/service cases pass, including saved-note service,
  unsafe-edit refusal, duplicate identities, coincident geometry and raw XFA.
- Production-static Chromium154.0.8037.57 with real PDF.js and packed writer tests
  all-document/reply display, author/body filters, exact saved/pending card targets,
  edit/delete/undo/redo, reverse/delete page projection, sidebar exclusivity and
  nonmutating view actions. Worker-message faults delay page reads and fail one page;
  observed source page reads are `[0,1,2,2]`, proving successful-page reuse and retry.
  Delayed preview text reads verify immediate list clearing, readonly actual preview,
  return to source, save/download, readonly revision reopen and mobile close.
  Authorization/revision routes substitute persistence; this is not deployed auth/SQL.
  The affected View browser scenario also passes source control order, night mode,
  zoom/anchor, readonly controls and unfiltered print canvas with unchanged bytes.
- Independent pypdf reads the actual source/download and verifies output order1,0,
  unchanged page content/text/boxes/rotation/UserUnit, form values/widget appearance
  streams, original root/reply dictionaries and /IRT. Only the edited control note's
  Contents/M changes; pending note is added and deleted page is absent from output.
  Raw references independently match inspect sourceRef, and linked notes are readonly.
- Node22.23.4-slim mounts the packed runtime/input readonly with network disabled:
  inspect metadata/thread boundaries pass, sourceRef-as-write request refuses without
  an output file, and replay of actual browser operations produces byte-identical
  download. This does not replace full application-image acceptance.
- Final Standard37.55s/Slides36.68s builds and the configured Standard budget pass. Slides has no equivalent configured budget. Standalone
  bridge typing retains six baseline desktop declaration diagnostics, zero new.
  Thirty-six local engine hashes and date-parser extraction hash pass. Existing
  chunk-size warnings remain; no full suite is repeated.

Runtime CLI SHA256:
`30bdc75e5e6a00a4e6a4dd441df7a1fa47abe654da6a569689b2e49d872881d8`.
Browser source SHA256:
`a9341e9e390435f0ab0fb087d75bf658de64d8f770a4116e8a39109faef4100c`.
Actual download SHA256:
`a28a704b8ce1c10128afedb762e25665839a66a82e36c916bc4cf643ba1fbe5c`.
Evidence: `/workspace/scratch/pr190-pdf-comments-evidence.zip`.

The archive retains initial type/build and timing-test failures and corrected
independent-reader setup/dictionary-normalization failures. The old preview-list
race was fixed before the final deliberately delayed preview passed.

## Remaining boundaries

Reply/thread writing, rich-text editing, full source popovers/context, resizable/
persisted sidebar, comparison/attachments and whole PDF parity remain open.
Desktop compatibility, full-image ENOSPC and deployed identity/network acceptance
remain open. Certificate signing still needs an authorized backend/certificate
contract. No feature flag is enabled and no merge/deploy acceptance is claimed.
