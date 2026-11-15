# Native PDF pending-note actual-preview/time acceptance

2026-11-06–07. Closes the pending-only actual-output preview and creation-time binding
gap from `NATIVE_PDF_PENDING_NOTES_ACCEPTANCE.md`. Whole PDF parity remains incomplete.

## Primary source and counterexample

Fixed GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d` captures createdMs
  when adding a note; setNoteContents preserves its drawing/creation instant.
- save-pdf.ts blob `4713ad820f4854479cdf73a9586051631f79de73`, lines50,
  499–512,645–669: rects round to two decimal places, pdfDateString uses the
  worker's local timezone, and new notes write CreationDate/M from
  createdMs ?? Date.now(). Notes append one annotation per drawing after markups.

A direct call to that unchanged vendored writer shows why staging an instant alone
is insufficient. For createdMs1793970000123, UTC writes
`D:20261106130000+00'00'`; Asia/Tokyo writes `D:20261106220000+09'00'`.
These are the same instant but produce different PDF bytes:
`087898b759a9ee9de75163e96e9310f27cd24a851f7a58189e608eadd24f70e1`
versus `7864ceda4afcb9ccb13f06ac7f145bfe44ac51dc5745af7f685f7eb870d05170`.
Untimed source additions also differ. The original PDFs/receipts are retained in
`upstream-counterexample`; this is a source behavior counterexample, not a native
success or a claim that the original file was corrupt.

## Native contract and adaptation

The existing addTextAnnotation operation gains optional createdMs: an integer
0–253402300799999 (1970 through year9999). Pointer placement captures Date.now once.
Edits, history and reload retain that value. This is client-supplied document
metadata, not an independently attested audit clock. PDF dates retain whole seconds.

The unchanged pinned drawing/AP writer receives the staged instant. A small native
post-write adapter canonicalizes only the appended new note dates to UTC before
crop/final paper transforms. It validates base count + requested markups + requested
notes, source-to-output page mapping, indirect annotation type/contents and its
pinned two-decimal Rect before touching dates. A missing append must not relabel an
identical existing note; unexpected counts/payloads refuse before output creation.
All surviving page counts are checked, including untargeted pages, so shared-array
collateral appends refuse. Original annotations/dates, AP streams and other dictionary fields are preserved.
No global timezone or Date override is used by product code; vendor files stay unchanged.

Legacy requests/drafts without createdMs remain supported. Their actual creation
instant is unknown: optional CreationDate/M are omitted on those newly written
notes instead of inventing a timestamp. The writer receives a temporary deterministic
value, then those dates are removed before any result file is emitted. Existing
source notes retain their metadata. This is an explicit compatibility adaptation
from the previous save-time clock behavior, and avoids silently upgrading old
records with a false creation time. New and legacy additions now have stable bytes.

Service preview returns the actual receipt independently of the text feature flag;
its digest includes actual output SHA for new notes. The existing preview.pdf path
rebuilds and verifies that digest. The UI opens the actual PDF for pending-only
notes, reads its annotation bodies through PDF.js, labels them “预览批注” and keeps
preview controls readonly. Returning to source restores pending controls. Changed
text invalidates/rebuilds the preview; saved output/download matches the latest
preview bytes. No new checkbox/approval or mandatory note-preview save gate was added.

## Verification

- 14 new actual-file cases across focused runs: timed/legacy determinism under
  three worker timezones and three simulated wall clocks, old date preservation,
  page content/text/forms/AP, invalid explicit times, range extremes, mixed source
  edits/markups/form/crop/rotation/delete/reorder, final paper transform and fractional
  placement, actual new-note/text replacement and collateral appends via shared
  indirect Annots arrays. Two existing file cases cover original annotation/page roundtrip and
  source-note/text-rewrite composition. Repeated affected selections are not recounted.
- Two new writer-drift guard cases exercise missing append, unexpected payload and
  missing output-page refusal. Six new frontend checks plus51 affected checks pass:
  creation instant preservation/legacy absence and malformed restored-time refusal.
- Two new real service cases (timed/legacy) plus three affected markup/saved-note
  service cases pass. Preview in UTC, preview file in Asia/Tokyo and save in
  America/Los_Angeles have equal bytes; changed creation input refuses the old
  digest. Registered output retains download despite business validation warning.
  Service repository/auth scope are synthetic/in-memory, not production SQL evidence.
- Production-static Chromium154.0.8037.57 uses real pointer placements and PDF.js,
  preserves creation through edits/history/reload and an advanced browser clock,
  renders pending-only actual preview, repeats equal bytes after reload, edits text
  and renders changed bytes, saves/downloads exact latest-preview bytes and reopens
  saved notes. It also repeats stale detached-control, readonly and page-history
  guards. Auth/revision routes substitute persistence; the packed writer executes.
- Independent pypdf verifies preview/download equality,750→800 changed note text,
  UTC CreationDate/M, original note dictionary and all page content/text/boxes/
  rotation/UserUnit, form values/widget appearances preserved. Source is UserUnit2
  with offset CropBox and a rotated page; output order is original1,0.
- Final Standard32.51s/Slides31.56s builds include strict frontend types; budgets,
  Ruff, smoke syntax/diff and35 local hashes pass. Standalone bridge typing retains
  six baseline desktop declaration diagnostics, zero new; not a clean standalone check.
- Final Node22-slim read-only/network-none runtime passes timed Tokyo/Los Angeles
  byte equality with the browser download, legacy unknown-date equality with host,
  invalid timestamp refusal and shared-array collateral-append refusal without an output file. Mounted runtime tests do
  not close full application-image, desktop or production acceptance.

Accepted runtime CLI SHA256:
`1a2c71dc2638cafa801672263d23e9d7831d912c89a7df662bc308c383ea6a12`.
Browser source SHA256:
`f312712284c78d3356817db1a70fc28b6cb0cf2a90cddb76acb6bd2adae94a9a`.
Repeated first-preview SHA256:
`94798ed8b4f5b30d1ec4737c93d5f05d9b1115c3dbae086cfba46f60d617c9ee`.
Changed final-preview/download SHA256:
`b81f68dd43bf19b53565713b7a2ad16649fc084caa31241e233bb50d147d6ea8`.
Evidence: `/workspace/scratch/pr190-pdf-note-preview-evidence.zip`.

The fractional guard was corrected after primary-source review to match pinned
num rounding. The environment resumed on2026-11-07 with workspace code intact but
pre-resume /tmp evidence lost. Those old test/probe logs are not in this archive
and are not treated as final reproducible evidence. Final scoped checks, browser,
independent readback, runtime/container checks and source counterexample were
recreated under persistent scratch storage. The final append guard also checks
untargeted survivors. No whole suite was repeated. A local evidence-script naming
collision with Python's types module was corrected without product changes.

Still open: replies/threads, richer/locked/shared-source mutations, complete
sidebar/context, exact desktop compatibility, full image and production identity/
network. Saved-note edit M has its separately staged edit time. No whole-PDF or
signing completion is claimed; flags remain off.
