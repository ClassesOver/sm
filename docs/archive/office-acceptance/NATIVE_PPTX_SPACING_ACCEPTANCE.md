# PPTX paragraph spacing acceptance

## Delivered slice and scope

Native PPTX Home Paragraph now exposes six source line-spacing choices (1, 1.15, 1.5, 2, 2.5, 3 times) and before/after point spacing. Each visible control uses `onParagraphFormat`; values apply to all paragraphs in the selected editable text object, matching the existing engine's element-wide operation. They are not a rich-text caret-range editor or new table/group-child support.

Wire records in `editSlides.paragraphFormatting` require `slideIndex`, `elementId` and at least one of:

- `align`: left/center/right/justify, retaining the existing operation.
- `lineSpacingPct`: exactly 100/115/150/200/250/300.
- `spaceBeforePt` / `spaceAfterPt`: finite numbers from 0 through 500, including explicit zero. The pinned engine writes hundredths of a point; the UI uses the same rounding.

Python and direct bridge entry points reject booleans, nonfinite values, unknown fields, empty patches and invalid targets. Only explicitly supplied fields reach the unchanged GenOffice `setElementParagraphFormat` setter. Ordinary report-editor save validation is not widened; these controls are in the native PPTX view.

The inspector retains `paragraphAlignments` and adds a per-paragraph `paragraphFormatting` array, including exact line points and percentage paragraph-spacing alternatives. Missing values stay null. Mixed/unset/other-unit source values are blank with an explanation; no 100% or 0pt default is fabricated. Pending updates override only the selected field. Restoring multiple records for one object merges fields rather than discarding an earlier alignment record. Selection changes, Undo/Redo and refresh retain this state model. Controls are disabled without an editable text target and while saving/closed.

## Evidence

| Layer | Result |
| --- | --- |
| Backend and native schema | 52 targeted cases passed, 26 deselected. Includes six line choices, unit alternatives, 0/500 boundaries and hundredth-point rounding, align-only preservation, unknown fields and invalid targets |
| Independent file readback | python-pptx plus ZIP/XML verifies paragraphs, font/bold, bullet and RTL preservation, untouched objects/slides and original non-target ZIP parts. The edited shape may receive the fixed engine's existing `a16:creationId`; preservation comparisons exclude that metadata and explicitly changed paragraph properties, not arbitrary differences |
| Frontend | 43 targeted cases passed, followed by 3 affected spacing/restore cases after fixing same-object record merging; TypeScript checks passed |
| Final builds | Standard and Slides production builds, actual chunk budget and budget contract passed after the visible spacing labels were added; existing third-party chunk warnings remain |
| Independent review | Separate real PPTX probe combined page reorder with four records on the original object: 115% line spacing, before 0, right alignment and after 500. python-pptx confirmed correct target and Arial/bold preservation; no further confirmed defect found |
| Native browser | Chromium 154 input preflight and spacing smoke passed: mixed source values, comma-decimal Enter input, invalid input leaving draft unchanged, explicit zero, align merge, Undo/Redo, selection switching, actual refresh, save/download and revision-2 reopen |
| Packaged HTTP | New spacing and custom-size/text operations passed the existing PPTX ASGI roundtrip in Node 22, read-only `--network none` container using the separate production-packed engine (1 passed, 9.86s) |

The browser fixture contains two paragraphs with different original spacing, plus an untouched text object. Independent python-pptx readback confirms 200%, before 12.5pt and after 0 on both selected paragraphs, while preserving bullet/RTL and the other object's entire XML. Source and preview identities now use actual fixture bytes rather than placeholder hashes.

The HTTP test additionally retains capability/session/CSRF, validation-failure download, SHA, idempotent retry and revision reopen assertions. Its repository is an in-memory substitute. Browser authorization/revision routes are substitutes; actual file engines and independent readers run. These are separate scoped proofs, not production database/TCP/TLS, full application-image or Office GUI layout certification.

## Reproduction and retained samples

From the repository root, with existing lockfile dependencies installed:

```sh
(cd smart_reporting/reporting/slides_engine && npm run bundle:bridges -- --metafile=dist/metafile.json)
node docker/package-office-engine.mjs smart_reporting/reporting/slides_engine /tmp/pr190-pptx-spacing-runtime
(cd smart_reporting/report_editor/frontend && \
 REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
 AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-pptx-spacing-runtime \
 PPTX_SMOKE_MODE=paragraph-spacing \
 PPTX_SMOKE_EVIDENCE_DIR=/tmp/pr190-pptx-spacing-evidence \
 node smoke/pptx-native-save-smoke.mjs)
```

Host ASGI equivalent:

```sh
AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-pptx-spacing-runtime \
AGENT_WORKSPACE_HMAC_SECRET=test-only-workspace-secret-0123456789 \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest \
 'smart_reporting/reporting/tests/test_native_ribbon_http_roundtrip.py::test_ribbon_operations_use_real_http_save_download_and_reopen[pptx]' -q --tb=short
```

For the isolated variant, use the Python/source mounts and network flags in `NATIVE_RIBBON_OFFLINE_ACCEPTANCE.md`, mount this runtime at `/opt/reporting-slides-engine`, and run only the PPTX node ID. Runtime base remains Node `v22.23.4`, manifest `node@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d`.

Local artifacts: `/tmp/pr190-pptx-spacing-evidence/{source.pptx,downloaded.pptx,evidence.json}`. Successful sample source SHA: `91c8e50829321360d6ab5b639b16bcdc9727ab991058f5e904afade668247983`; download SHA: `e1945edd97eb54d0aac8d5f125871b121cebcd8de9229341785e784eed3ac944`. Fixture metadata may change hashes between runs; every run verifies its own identities. Logs: `/tmp/pr190-pptx-spacing-browser.log`, `/tmp/pr190-pptx-spacing-http.log`.

## Remaining work

This closes spacing controls only. Bullets/numbering, indentation and direction commands from the source inventory remain incomplete. Complete source-tab/context parity, clean full application image and image-hosted browser acceptance, production database concurrency and external-host integration remain open. The previous 8GB/vfs full-image build failure is still a resource blocker for that boundary. Features remain off; no merge/deployment occurs.
