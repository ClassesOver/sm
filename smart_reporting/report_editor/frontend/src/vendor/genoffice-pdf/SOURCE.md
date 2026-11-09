# GenOffice PDF renderer sources

Upstream: https://github.com/genspark-ai/genoffice at `f8c17004fb730df11f0f743164ffd8b4281bb38c` (Apache-2.0; `LICENSE`/`NOTICE` alongside).

| Local file | Upstream path | Status | SHA-256 |
| --- | --- | --- | --- |
| `renderer/stamps.ts` | `apps/pdf/src/renderer/stamps.ts` | byte-identical | `e8b57e2ac9ae8bc022753ce992da44b2ba7e62bc924901fc44df761a98509e88` |
| `shared/ipc.ts` | `apps/pdf/src/shared/ipc.ts` | adapted: only `StampInput` | `d182b3245644fafa8a75e3de0a274c25828311ea24cdbfb5a75dea443f6cb37a` |

`stamps.ts` rasterises the watermark and header/footer bars with a browser canvas and builds
`StampInput`s (`buildStamps`, `DEFAULT_WATERMARK`, `DEFAULT_HEADER_FOOTER`). The native editor
uses it unchanged for Edit ▸ 水印 (pinned `StampDialog` → `setStamps`), then offsets each rect by
the page CropBox origin and sends the PNGs to the PDF bridge, which hands them to the pinned
engine's `stamps` stage.
