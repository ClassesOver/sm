/** Compatibility entry for the image-only adapter; shared pointer lifecycle is in drawing-canvas. */
import { mountDrawingCanvas } from './pdf-drawing-canvas'
export type { DrawingCanvasController as ImageCanvasController } from './pdf-drawing-canvas'
export function mountImageCanvas(options: Parameters<typeof mountDrawingCanvas>[0]) { return mountDrawingCanvas({ ...options, imagesOnly: true }) }
