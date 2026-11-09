# PDF embedded attachment read/export acceptance

2026-11-09; bounded continuation of PR #196, following merged PR #190.

## Primary material and behavior

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:
`apps/pdf/src/renderer/AttachmentsPanel.tsx` and App.tsx (blob
`e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, attachment census/export and
View/sidebar wiring). Full original files and their SHA256 are retained;
`genoffice-pdf-attachments-source.json` records provenance and native adaptations.
The source humanBytes formatter is extracted unchanged.

View attachments now opens an exclusive sidebar alongside thumbnails/outline/
comments. It displays saved attachment names, descriptions and actual byte sizes,
with explicit content/metadata read failures and retry. Empty attachment content
is a valid zero-byte download; absent/unreadable content is an error, not zero.
The UI states that add/remove is unavailable.

PDF.js Map keys are attachment identities, distinct from filenames: two different
keys with the same display basename retain separate content/cache/download targets.
Metadata and byte promises are cached per PDF.js document; successful/inflight
reads share work and rejected reads retry. Source and actual-output preview are
separate documents. Generation guards reject abandoned/old-document download
buttons; refresh/preview switches clear old lists before replacing the document.
Rows render with textContent. User-triggered downloads use an octet-stream Blob,
basename-only suggested filename and delayed URL release; disposal clears timers
and revokes outstanding URLs. Files are downloaded without automatically opening.

## Authorization and API boundary

Extraction uses the already-authorized, source-SHA-verified PDF loaded by the native
editor, which already contains these bytes. There is no new server route, external
file path access, artifact registration, signature link or native write operation.
Readonly revisions allow viewing/downloading; no draft operation is created by it.
The desktop export dialog is adapted to a browser download. Add/remove and complete
desktop attachment workflow are not credited as implemented.

## Evidence

- Four new frontend cases cover duplicate filename/different-ID targeting,
  inflight/success cache, empty binary content, metadata/content retry, inline
  bytes, absent/malformed data, document isolation/reset, source size formatting
  and basename normalization. Nine affected comments/View checks pass; the initial
  test-file creation used the wrong working-directory path and was corrected.
  The initial selection ran only the nine affected checks; new checks are counted
  from the separate four-case run, not inferred from its command text.
- Production-static Chromium154.0.8037.57 uses actual PDF.js6 and the real packed
  engine. Four attachments include two distinct same.txt files, empty.bin and a
  76,800-byte Unicode-named binary. All four browser downloads match expected bytes.
  Worker injection fails metadata once and content once and delays the shared list
  request across close/reopen. Reads show two directory requests and five content
  requests, so retry does not reread successful content. Failure states, exclusive
  sidebar, escaped descriptions, obsolete buttons, actual-preview document isolation,
  return to source, saving a new note, readonly revision download, mobile close and
  a separate no-attachment document all pass. View actions leave the draft unchanged.
- Independent pypdf extracts original and saved attachment bytes and compares every
  hash with browser downloads. Entire catalog Names, descriptions and embedded-file
  streams match. All three pages retain content/text/boxes/rotation/UserUnit, fields/
  widget appearances and original notes; the requested new note exists.
- Affected comments and View browser scenarios pass, including delayed-preview
  clearing, exact note navigation/history, night mode, zoom/anchor and print canvas.
- Final Standard36.23s/Slides39.35s builds and both budgets pass. Smoke syntax and
  git diff checks pass; primary-source hashes/unchanged formatter are verified.
  No backend/runtime/dependency source changed and no whole suite was repeated.

Browser source SHA256:
`c38dd0037fe6ee3fdeb45876d334195f0ba97c153ce8551e1e0c2e4a2a531639`.
Saved PDF SHA256:
`e51e770bbc29db6b685a4c3d2ac2f449594af157724fb061823ab9748d3365a6`.
Unchanged packed runtime CLI SHA256:
`30bdc75e5e6a00a4e6a4dd441df7a1fa47abe654da6a569689b2e49d872881d8`.
Evidence: `/workspace/scratch/pr196-pdf-attachments-evidence.zip`.

Browser authorization/revision routes substitute persistence. This is not
production SQL/auth or desktop download-dialog acceptance. Existing Node22 results
are not counted as new runtime checks. Attachment mutation, comparison, full PDF,
full application image and deployed identity/network remain open. Flags stay off.
