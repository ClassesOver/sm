# PDF bounded attachment add/remove acceptance

2026-11-09; continuation of PR #196 after merged #190. This closes safe flat-tree
attachment writing, not all PDF or desktop behavior.

## Primary materials and deliberate adaptations

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:
`AttachmentsPanel.tsx`, App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`
(attachmentRows/add/remove/export) and `apps/pdf/src/main/pdf-attachments.ts`.
Full primary files are retained in the evidence archive. The writer is reused
unchanged: SHA256 `7de34150d811b478678e74c196740ff19b326b49d10fc8c7f5360941f0486bec`.
All21 vendor modules match the preceding HEAD;18 match original upstream hashes
and the three previously documented adaptations remain unchanged. The current
LOCAL manifest verifies38 entries. No dependency/WASM/vendor writer change.

The source writer removes before adding, keys by the EmbeddedFiles name-tree key
instead of /F or /UF and preserves surviving Filespec objects. Its decoded-label
sorting is insufficient for mixed literal/UTF16 strings: the native adapter sorts
actual encoded string bytes after calling it. A real fixture and independent
pypdf verify ASCII `source-key` precedes UTF16BE `a.txt`, rather than sorting by the
visible label. Other catalog Names branches are preserved.

The native sidebar reuses the source pending-add/remove/keep behavior with a web
file picker and NativeDraft history/storage. It also keeps explicit description,
content-read retry and original-byte downloads. Unlike the source pane, a pending
removal still permits downloading the original file, and filenames are sanitized
only for the browser download name. Pending adds display actual decoded size.
There is no new backend upload/signing route: payloads use the existing draft,
preview and immutable-revision publication protocol.

## Exact scope and failure behavior

- Strict operations: addAttachment(name, canonical bytesBase64, optional
  description/sourceSha256); removeAttachment(attachmentId,
  expectedAttachmentSha256, optional sourceSha256). Extra fields are refused.
- Deletion identity binds immutable source SHA, tree position/key, Filespec and
  stream dictionaries, raw stream hash and decoded content hash. Equal display
  basenames retain independent targets. Stale/forged/duplicate identities fail.
- Names must be nonblank, valid Unicode, at most256 UTF16 units, without path
  separators or control characters. Empty content is valid; malformed/noncanonical
  base64 is refused. Added decoded bytes:2 MiB/file,6 MiB/batch; resulting entries
  at most200. Existing500-operation/12 MiB JSON budgets still apply.
- Source census: at most20,000 indirect objects,200 attachment entries,8 MiB
  decoded/file and24 MiB decoded total. Only unfiltered or single Flate streams
  without decode parameters are supported; inflate has a hard output bound.
- Hierarchical Kids trees, ambiguous keys/direct Filespecs, shared containers/
  references/streams, associated AF/AFRelationship/FileAttachment sources,
  signature/ByteRange, signature fields, XFA or catalog permissions are readonly.
  This is a conservative write boundary; PDF.js viewing/download stays available.
- Page/form/note processing runs first. Attachment writing checks that all source
  attachments survived the intermediate bytes, then verifies final survivors and
  each added payload/description. Attachment-only edits bypass unrelated save
  writer work. replaceText mixtures are refused pending preservation evidence.
- Local asynchronous reads capture the whole draft and document identity. Undo,
  source/preview switch, saving/closed/readonly/printing state or disposal cannot
  append an obsolete result. Restored operations are validated before editing.
- **Removal only removes the directory entry. Original objects can remain in the
  PDF; this is not secure erasure.** The UI states this. The existing24 MiB online
  source ceiling is unchanged; a larger generated output can still download but
  is outside online reopen scope. Business acceptance warnings remain nonblocking.

## Verification and independent witnesses

Seven new real engine cases cover add/remove/replacement, equal basenames,
empty files, byte sorting, deterministic receipts, preserved source metadata,
form/note/rotation combinations, stale/forged identity, collisions, schema and
byte budgets, malformed/shared/linked/protected sources, Flate preservation and
bounded decompression. Three affected existing engine cases pass, including no
output creation after a later invalid operation and exact form-field identities.

Four new frontend cases plus21 affected cases pass (25 total). A production-static
Chromium154.0.8037.57 compound scenario verifies real file selection, pending
remove, undo/redo, exact local draft reload, duplicate-name rejection, gated file
read with intervening undo, actual preview/return, save/download and readonly
reopen. It preserves previous metadata/content fault injection, precise cache
counts, equal-basename/empty/binary downloads, abandoned download controls and
mobile pane checks. One directory removal and one6-byte binary addition survive
save, together with the explicit note; no stale file read becomes an operation.

Seven selected actual service cases pass: the new attachment preview/digest/
save/download test plus existing note/markup/page-size cases. Changed preview
payloads are rejected, source bytes remain unchanged and failed business validation
still yields a readable saved download. These are controlled service fixtures,
not production authorization/SQL acceptance.

Independent pypdf extracts and compares the actual browser output. It confirms
folderA/same.txt is removed while folderB/same.txt retains its distinct original
bytes; empty.bin and 报告.bin remain; zz-new.bin contains exactly
`00 01 02 ff 80 0a`. Original page content/text/geometry, form values/widget AP,
original notes and other Names branches remain intact. The explicit new note
exists, and raw name-tree keys are byte-sorted. pypdf exposes both tree key and
/F-/UF-name aliases in the deliberately mismatched-key engine fixture; assertions
respect that independent-reader behavior rather than assuming one dictionary key.

The packed bridge SHA256 is
`906702bcfe3d5f0f537cb34454af4bb30d34f67429b02c40ca7b57b64a8783c8`.
It writes a real attachment in Node22-slim with network disabled and runtime
mounted readonly. Independent pypdf verifies those bytes and preserved source
attachment/form values. This is a mounted-runtime check, not a full application
image test. Standalone bridge typing remains6 existing desktop diagnostics with
zero new; it is not reported as a clean standalone typecheck.

Standard/Slides final builds, configured Standard asset budget, local/vendor
identity checks, smoke syntax and diff checks pass. Slides has no equivalent
configured budget. No whole repository suite was repeated. The browser exposed
an early model access in the new button initialization; a document-ready guard
fixes it. A test selector was also corrected to open the Home tab before clicking
its undo/redo controls; application assertions were retained.

Final browser source SHA256: `41acf697047e3436d4f1c6fbea2b6a737db00c6d65520fd310ee5f3a8ea13708`.
Actual downloaded output SHA256: `9a679ff595aded84986f221853ee317f688250165fc9d0f32b8de58ef91f2406`.
Standard39.69s/Slides37.37s builds pass.

Evidence: `/workspace/scratch/pr196-pdf-attachment-write-evidence.zip`, including
primary sources, generated/actual downloaded PDFs, independent script/results,
packed runtime, browser and focused engine/service/build records.

Complex attachment structures, full desktop file/export behavior, reply writes,
other PDF feature families and full image/production/desktop acceptance remain
open. Feature flags stay off; no merge or deployment is claimed.
