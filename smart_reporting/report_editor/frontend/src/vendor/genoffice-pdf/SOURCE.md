# GenOffice PDF renderer sources

Upstream: https://github.com/genspark-ai/genoffice at `f8c17004fb730df11f0f743164ffd8b4281bb38c` (Apache-2.0; `LICENSE`/`NOTICE` alongside).

| Local file | Upstream path | Status | SHA-256 |
| --- | --- | --- | --- |
| `renderer/stamps.ts` | `apps/pdf/src/renderer/stamps.ts` | byte-identical | `e8b57e2ac9ae8bc022753ce992da44b2ba7e62bc924901fc44df761a98509e88` |
| `renderer/measure.ts` | `apps/pdf/src/renderer/measure.ts` | byte-identical | `4d2ccdb5cc2bb69703a6e0e7fe708a49e1101d001ab75c220913c0dd0670e6dd` |
| `renderer/image-bake.ts` | `apps/pdf/src/renderer/image-bake.ts` | byte-identical | `bf1b8eaab654e42e80092ed66044e21dd95efb77376798de9e23459151743f50` |
| `renderer/cutout.ts` | `apps/pdf/src/renderer/cutout.ts` | byte-identical (only `PixelImage` is used) | `907bf9b770b660cdfca6d80ae91e2aed8f89a11831f4eeb023b2f73486b9a26e` |
| `shared/ipc.ts` | `apps/pdf/src/shared/ipc.ts` | adapted: only `StampInput` | `d182b3245644fafa8a75e3de0a274c25828311ea24cdbfb5a75dea443f6cb37a` |

`stamps.ts` rasterises the watermark and header/footer bars with a browser canvas and builds
`StampInput`s (`buildStamps`, `DEFAULT_WATERMARK`, `DEFAULT_HEADER_FOOTER`). The native editor
uses it unchanged for Edit ▸ 水印 (pinned `StampDialog` → `setStamps`), then offsets each rect by
the page CropBox origin and sends the PNGs to the PDF bridge, which hands them to the pinned
engine's `stamps` stage.

`measure.ts` provides the calibrated measure tool's `parseCalibration` / `formatLength`; the native editor keeps
the scale for the session only (as upstream) and writes the formatted label into the engine's `measure` drawing.


## Selection style helpers (2026-11-11)

Local ../../pdf-selection-style-source.ts copies apps/pdf/src/renderer/color-runs.ts at the same pinned ref. The helper body is byte-identical; only an initial provenance comment is added.
Upstream SHA256: 38139b354fb401b27c00487423eb4b7548f66a1692cbda35f0f1d28d16808bc9.
Local SHA256: 7ed330f5f5cf5ec0f7c5dcb3419cf5b0cd00728a3fa08a3cf4582da5f69d4382.
Existing Apache-2.0 LICENSE/NOTICE apply. These are UTF-16 style patch/splice helpers, not a new layout engine.

2026-11-11: local host adapters preserve the fixed App.tsx Ctrl/Cmd+Enter replacement submission through the existing guarded button, and add fixed FormDesignLayer/App single-widget canvas selection and 1/10pt keyboard nudge using the existing identity-bound rect operation. Safe sources remain default UserUnit only; shared fields, drag/resize and arbitrary mixed drafts are not enabled. Local UI helpers and styling are not upstream source files, and fixed upstream hashes remain unchanged.

`image-bake.ts` supplies `cropRect` for the existing-image crop footprint so the draft rect equals what the
PDF bridge recomputes from the same pinned function (the bridge vendors the same file under `reporting/pdf_engine/src/renderer/`).
