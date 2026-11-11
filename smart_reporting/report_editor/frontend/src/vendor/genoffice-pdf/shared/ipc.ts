/**
 * Adapted from GenOffice apps/pdf/src/shared/ipc.ts at f8c17004fb730df11f0f743164ffd8b4281bb38c:
 * only the `StampInput` interface used by renderer/stamps.ts, copied verbatim. The desktop IPC
 * channels and other request types are not part of the browser closure.
 */
/**
 * Stamp layer (watermark/header/footer/page numbers all go through it).
 * The renderer rasterizes the bitmap via canvas (with rotation and fonts, bypassing
 * pdf-lib's lack of CJK support); the main process only embeds and positions it.
 */
export interface StampInput {
  pageIndex: number
  /** base64 PNG, without the data: prefix */
  image: string
  /** PDF user space [x1,y1,x2,y2] */
  rect: [number, number, number, number]
  opacity?: number
}
