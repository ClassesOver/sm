# Native PPTX transition metadata preservation

2026-11-06. This closes the confirmed native single-page effect-change metadata
loss described in `NATIVE_PPTX_TRANSITION_ALL_ACCEPTANCE.md`. It does not certify
all transitions, playback, desktop compatibility or full source ribbon parity.

## Original material and implementation

The pinned `packages/pptx-engine/src/generate.ts:patchSlideTransitionXml` replaces
the complete transition container and restores only advTm. The old real-file
speed/click/sound loss probe remains valid evidence of that upstream behavior.
Vendor files and their source manifests are unchanged.

The native bridge now calls `bridge/pptx-transition.ts`, a preservation adapter
using the pinned effect generator and existing XML segment/child utilities. It
retains original opening attributes and sound/extension subtrees, replacing only
the visual effect. The upstream setter still establishes the dirty/save hook;
then the bridge installs preserved XML. Removing the effect retains metadata;
reapplying the same effect leaves the original suffix exactly unchanged.

Supported sources are an ordinary transition or the pinned Morph compatibility
shell (one p159 Choice with its local 2015 namespace and one Fallback, each with
one transition). Ordinary-to-Morph copies metadata into both branches; subsequent
changes retain their individual settings and the wrapper. Unmodeled effects,
duplicate containers, arbitrary AlternateContent, comments/processing instructions
and ambiguous markup are readonly. Inspect reports this explicitly; sidebar,
Ribbon, forced dispatch, draft recovery and backend requests enforce the boundary.
The inspect effect comes from the actual child, not a morph-like extension name.
The separate, stricter Apply-to-All source gate remains unchanged.

## Independent evidence

`reporting/tests/test_pptx_transition_preservation.py` constructs real ZIP/PPTX
fixtures with speed, click/automatic advance, p14 duration, namespace attributes,
literal replacement-string characters, sound action, a real WAV part and audio
relationship, extension data, shapes and timing. python-pptx, lxml and ZIP reads
verify every container attribute, non-effect subtree, audio/relationship bytes,
untouched slide bytes and package integrity independently of the writer.

- 29 distinct new backend cases passed across targeted runs: 12 effects times
  ordinary/pinned-Morph sources, exact same-effect/noncanonical quotes, opaque
  extension identity, and three unsafe-source refusals.
- Initial runs exposed a missing upstream dirty hook, then a comparison polluted
  by unused inherited namespaces. The hook was fixed; metadata subtree comparison
  uses exclusive C14N. Refusal checks assert the public normalized API error.
  Successful targeted reruns and earlier failures are retained; reruns are not
  counted as additional distinct cases.
- All 20 existing Apply-to-All actual-file cases passed.
- Four new frontend checks plus one affected existing source-gate check passed;
  frontend and bridge strict TypeScript checks passed.
- Production-packed Node 22, readonly/network-none container: 3 selected checks
  passed (ordinary to Morph, pinned Morph to wipe, single-Choice refusal).
  This is a mounted-runtime check, not a full application image.

`frontend/smoke/pptx-transition-preservation-smoke.mjs` ran in Chromium
154.0.8037.57 with the actual packed engine. It changes fade to wipe, checks
Undo/Redo, reload recovery, unsafe-source disabled/forced dispatch, save revision
2, actual download and reopen. Independent readback verifies effect, all
attributes, sound/extensions, WAV/relationships and untouched slides. Authentication
and revision routes are test substitutes, not deployed authorization proof.

Source SHA256: `ca348ccc66a7bd6ff393e5aa0778886cae4b327cda3368bb4debdf57be0c6b79`.
Download SHA256: `80a0a8673b0497431a0c297ea145171c02bfd4be57e574b9c226b56ab84bfb3d`.
Browser originals and receipt: `/tmp/pr190-transition-preserve-browser-evidence`.
Logs: `/tmp/pr190-transition-preserve-*.log`. Evidence archive:
`/workspace/scratch/pr190-transition-preservation-evidence.zip`.

Both production frontend builds, actual bundle budget and budget contract pass.
Existing third-party chunk/circular warnings remain. Ruff, smoke syntax and
`git diff --check` pass. No full repository/frontend suite was repeated.

## Remaining boundaries

The direct upstream setter still has its original preservation limitation; only
the native bridge uses this adapter. Bulk remains deliberately more restricted.
No transition speed/sound editor, playback/audio validation, arbitrary MC support,
Office desktop proof, new SQL authorization flow or full application image is
claimed. Tasks 2–6 remain open and feature flags remain off.
