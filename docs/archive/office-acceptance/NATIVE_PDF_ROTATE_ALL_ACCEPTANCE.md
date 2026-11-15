# PDF rotate-all surviving pages acceptance

2026-11-06. Bounded Task 5 command closure; this does not complete the PDF ribbon.

## Original source and behavior

Read fixed GenOffice [`apps/pdf/src/renderer/App.tsx`](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/pdf/src/renderer/App.tsx),
blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`:

- Lines 5020–5028: `rotatePages(origIdxs, dir)` delegates through the editor's
  atomic operation path; `rotateAllPages(dir)` passes `visList`, not every original
  source index including deleted pages.
- Line 8909: the source button dispatches **`rotateAllPages(90)`**. It is disabled
  for an empty document or read-only state. This command is clockwise 90 degrees,
  not an arbitrary-angle or absolute-orientation dialog.

The native control keeps `genoffice.pdf.page.rotateAll` in the source Rotation
command group. It now uses `rotateAllPdfPages` and existing strict `rotatePage`
records. The existing PDF engine already adds each requested delta in order
(`src/main/save-pdf.ts`, rotation loop); no new backend schema, custom PDF writer,
server endpoint or vendor change was introduced.

## State, identity and constraints

`pdfPageState` obtains the surviving source IDs in the current draft order;
`rotateAllPdfPages` appends one `{kind:'rotatePage', pageId, delta:90}` per survivor.
Existing form values, source rotations, notes, deletes and reorder records remain
unchanged. The complete batch is passed to `NativeDraft.setOperations` **once**:
one Undo restores the entire prior snapshot and Redo restores all rotations.
Repeated per-page deltas retain their execution order and source identities.

The bridge's 500-operation limit is checked **before** changing draft state.
If the batch would exceed it, the control is disabled with a save/reopen/reduce
pages explanation; the pure helper also refuses it before persistence. It does
not silently skip excess pages or rotate only the first 500. A source document
with more than 500 survivors therefore cannot use this batch command within
this backend contract. Existing single-page operations remain distinct.

Loaded/editable/read-only, save/closed-revision, preview, print and operation-
budget locks apply. The handler independently checks those states. A changed
operation snapshot invalidates `PdfPreviewReview`; Undo does not resurrect an
old text-preview approval. Existing explicit text confirmation is untouched.

## Focused checks

- Initial local Vitest 3.2.7 selection: **17 passed** (16 operation cases and the
  source Page-group inventory). A subsequent atomic-draft/preview test raises
  the distinct selection to **18 cases**; targeted new/affected selections passed
  four cases, then the strengthened atomic test passed alone. Repeats are not
  added into an inflated count. No complete frontend/repository suite was run.
- New coverage includes reordered/deleted source identity, existing rotation,
  preservation of independent form operations, one NativeDraft Undo/Redo step,
  storage reload, exact 500 boundary, atomic over-budget refusal, stale/all-
  deleted state refusal and old preview-approval invalidation even after Undo.
- One initial command was mistakenly launched outside the frontend cwd, causing
  npx to begin fetching an unrelated Vitest version. That process was stopped;
  checks use the checked-in frontend's local v3.2.7 binary. No dependency or
  lockfile changed. The wrong-cwd/interleaved log is not passing evidence.

## Browser/file scenario

`frontend/smoke/pdf-rotate-all-smoke.mjs` creates four actual PDF pages with source
rotations 0/90/180/270, nonzero CropBoxes, an outline, an existing Text note and
four actual AcroForm fields. It uses the production-packed PDF engine through
`pdf_native` for inspect/patch, substitutes only browser authorization and
revision routes, and uses pypdf as an independent downloaded-file consumer.

The scenario stages four field values, a prior +90 on source page 1, deletes
source page 2, reverses survivors, then invokes the source rotate-all control.
Its added batch must target source pages **3,1,0** exactly once. It verifies one
Undo/Redo, true page reload and persisted-draft identity, save/download SHA,
independent values/rotations/CropBoxes/note, a fresh revision and read-only reopen.
Expected downloaded pages are:

| Source index | MediaBox size | Final Rotate | CropBox |
| --- | --- | --- | --- |
| 3 | 700×500 | 0 | [12,24,688,476] |
| 1 | 500×400 | 270 | [12,24,488,376] |
| 0 | 612×792 | 90 | [12,24,600,768] |

The original Text note remains on output page 1 at [30,60,50,78]. Independent
AcroForm readback requires name `Ada Lovelace`, consent `/Yes`, radio raw `/1`
with `/Opt` [basic,pro] resolving to pro, and region south. Checking only the
radio raw name against the human label would be incorrect PDF semantics.

Development runs completed the functional and file checks but **failed** their
strict console assertion: Chromium 154's local-network permission checks block
Vite development HMR WebSockets. These are not recorded as final acceptance.
The smoke supports `PDF_ROTATE_SMOKE_PRODUCTION=1` to use `vite preview` against
the coordinated production build; it keeps strict page/console assertions and
does not disable browser security or network restrictions.

The final production-browser run passed; its receipt and artifact hashes are
recorded below. The earlier `/tmp/pr190-pdf-rotate-all-evidence`
receipt is marked `accepted:false`; it must not be substituted for success.

Reproduction after a coordinated standard production build, from frontend:

```sh
PDF_ROTATE_SMOKE_PRODUCTION=1 PDF_FORM_SMOKE_PORT=4196 \
AGENT_REPORTING_PDF_ENGINE_DIR=/tmp/pr190-native-runtime/pdf \
PDF_ROTATE_EVIDENCE_DIR=/tmp/pdf-rotate-all-new-evidence \
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
node smoke/pdf-rotate-all-smoke.mjs
```

Complete application-image/browser, deployed HTTP/TLS, real SQL/grant storage,
production tenant authorization, signed-PDF and desktop/physical-print checks
remain outside this evidence. Other Page operations, Form Design and full source
parity remain open. No feature flag, deployment or certificate handling changed.


## Final accepted production-browser run

`PDF_ROTATE_SMOKE_PRODUCTION=1` passed against the coordinated production static
build (Vite preview, port 4196), Chromium **154.0.8037.57**, with strict application
page and console error assertions both empty. No browser safety flag or network
permission was disabled. The coordinated standard and Slides builds and both
budget checks passed at the root integration checkpoint; this worker did not
repeat those builds.

- Source SHA-256:
  `9c92a83c4c4def0ab27fb04caebc3364a34ab88715b654ffd7bf97eda9d10a72`.
- Download SHA-256:
  `70abf3b0359cfaabfbdb558ee6943177d85db202d37fbb99130b0dff263c5555`.
- Exactly **10 source-bound operations** saved: four field values, prior per-page
  rotation, source-page deletion, surviving reorder, and three bulk rotations.
- pypdf independently read output source order 3/1/0, Rotate 0/270/90, unchanged
  nonzero CropBoxes, all four field values with correct radio-option resolution,
  and the original note/rectangle on its surviving page.
- One batch Undo/Redo, true page reload/recovery, actual download hash, unchanged
  source bytes/default field, revision-2 reopen and read-only control state all
  passed.

Successful raw evidence is `/tmp/pr190-pdf-rotate-all-production-evidence` with
`accepted:true` and `productionBuild:true`; log:
`/tmp/pr190-pdf-rotate-all-production-browser.log`. It contains actual source and
downloaded PDFs, full operation identities and independent readback. The browser
authorization/revision substitutes remain explicit; no deployed-host, real
SQL/grant, signed-PDF, full application-image or desktop certification is claimed.
