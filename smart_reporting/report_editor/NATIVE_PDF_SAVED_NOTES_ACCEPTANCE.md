# Native PDF saved sticky-note editing/deletion acceptance

2026-11-06. Safe existing Text notes now support content editing and deletion.
Replies, threads, rich text and full comment/sidebar parity remain incomplete.

## Primary material and native boundary

Fixed GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`:

- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`,
  lines6394–6465: trim/nonempty note editing, replace a prior pending edit,
  drop an edit when source contents are restored, delete a note subtree and undo.
- save-pdf.ts blob `4713ad820f4854479cdf73a9586051631f79de73`,
  lines1646–1658: rewrite Contents with PDFHexString, update M with PDFString,
  preserve the original note object rather than delete/re-add. The source resolves
  by object number/rect/old contents and silently skips missing targets.
- annot-delete.ts blob `660951ad1e2556276245f64054af23fd4929e081`:
  object/geometry fallback; native saved-markup acceptance documents the stricter
  source-bound adapter used here instead.

New strict editNote/removeNote records bind source digest, original page identity,
annotation ordinal-derived identity and complete source dictionary digest. Native
code validates the entire request before serialization, then uses the source's
Contents/M primitives and existing exact-slot unlink adapter before subsequent
writer operations. It does not enable generic vendor annotDeletes or approximate
geometry fallback. Plain note edits preserve the original object number and other
entries; deletion copies the page's Annots array. No vendor source file changed.

The staged edit has a validated UTC modifiedAt (whole seconds). M is updated from
that stable value rather than Date.now during each rebuild, so the identical draft
has repeatable preview/download bytes and digest. This is an explicit native
adaptation to the preview protocol; the source writes save-time local-zone M.
Contents accept trimmed1–10000 characters. A note has at most one pending edit or
delete; duplicates/conflicts, stale revisions, forged hashes and extra fields refuse.

Signed/Perms/XFA, incomplete census, direct objects, shared annotation references,
IRT/Parent/Popup/structure-linked, RC/DS/DA/State/StateModel/RT and readonly/locked/
locked-content flags stay readonly. The simple UI edits saved note text through
an Apply/Cancel modal under each page's existing comments section. It shows virtual
pending text/counts, history/reload and actual output preview. Original canvas note
icons may remain until actual preview. Unsupported source identity can still show
PDF.js-extracted comments with disabled mutation controls. Readonly, preview,
save/print and closed revisions enforce mutation guards. This is not the source
threaded popup/sidebar or autosave UX; pending newly added note editing is not added.

## XFA source-census correction

Installed pdf-lib1.17.1 PDFDocument.getForm() calls deleteXFA() on its memory model.
Checking form.hasXFA() afterward therefore misses the original source's XFA. Inspect
now reads raw catalog AcroForm/XFA before getForm; that original flag protects
saved-note/markup removal, page-size capability and form-field editability. The
regression uses an actual XFA stream, forces valid-identity note edit/delete
requests and independently verifies original XFA bytes remain available. This
corrects a preexisting capability gap; it does not certify other XFA operations.

## Verification

- 23 distinct new actual-file cases across focused runs: Unicode Contents/M and
  exact other dictionary properties, stable repeated receipt/bytes, raw page
  content/text/forms/surviving markup AP, note-only deletion under rotation/
  other-page deletion/reorder, malformed/forged/overlong/timestamp/extra fields,
  eight readonly structures, duplicate/conflicting/late-invalid batches, actual
  text-replacement composition, duplicate geometry/content with separate IDs,
  forced malformed census and raw XFA protection. Seven affected saved-markup
  preservation/shared-array/identity/text-composition cases pass.
- Four new frontend cases plus34 affected markup/page cases pass: replacement/
  restore/delete, complete undo/redo/reload snapshots, readonly/deleted targets,
  operation budget and restored-record validation. New real service case plus
  two existing markup service cases pass: text flag off, actual preview, changed
  digest refusal, registered revision and actual download retained with business
  validation warning. After XFA correction, focused file/service roundtrip checks
  were repeated only where affected; retries are not counted as new cases.
- Production-static Chromium154.0.8037.57 proves modal cancel/source restore,
  Unicode edit plus deletion of another note, undo/redo/reload, actual preview,
  revision2/3 saves and downloads, reopen and readonly/preview controls. Independent
  pypdf sees note counts2→1→0, original edited object number, changed Contents/M,
  all content streams/text/page boxes/rotations unchanged and all form values/
  widget appearance states preserved. Auth/revision routes are substitutes;
  real service behavior is separately tested with an in-memory repository.
- Final Standard36.87s/Slides32.92s builds include strict frontend typing; actual
  budgets, smoke syntax, Ruff and diff pass. Local manifest33 items verifies.
  Standalone bridge typing retains six baseline desktop-declaration diagnostics,
  zero new; not a clean standalone typecheck.
- Final Node22-slim read-only/network-none mounted runtime passes edit+delete,
  delete both, forged identity no output and XFA-protected identity no output.
  Edit+delete bytes equal the actual browser revision2 download. The final runtime
  also reproduces both archived browser downloads after the XFA census correction;
  browser UI code did not change. This does not prove a full application image,
  installed fonts, desktop visual compatibility or production identity/network.

Final runtime CLI SHA256:
`985d30ccc45d8f1ef234d7f717d0c02be7ee9951faa0372f0da111780758f748`.
Browser revision1 SHA256:
`2869ff2c844523cf5042b577c958967b74a1e0b70082ee033ce8daedf690b7a1`.
Revision2 SHA256:
`782ec59bb6068fbf04474d5011d6226f9b6610c6b88c3113a39720e8c4b600c5`.
Revision3 SHA256:
`c03595bf457ce557bb5666fdf39cd7ea82db7d1f797058fe280a28983f50a451`.

Evidence archive: `/workspace/scratch/pr190-pdf-saved-notes-evidence.zip`.
Initial test failures came from constructing two independently timestamped source
fixtures, an incorrect expected form value, a missing second-page Annots fixture
and comparing pypdf reader-memory identities; corrected focused assertions pass.
The initial XFA container harness reused its source path as output and hit the
existing overwrite guard; the corrected distinct-output XFA request is refused
by the intended readonly identity gate with source bytes preserved. Raw failed
iterations and lint corrections are retained, not reported as passing.

Remaining: pending-note mutation, replies/thread edits/deletion, rich/locked/shared
source adaptation, complete sidebar/popups/context, desktop/full-image/deployed
acceptance and whole PDF alignment. Removing notes unlinks references; it is not
secure erasure/redaction. Flags stay off; see `NATIVE_PDF_ALIGNMENT_STATUS.md`.
