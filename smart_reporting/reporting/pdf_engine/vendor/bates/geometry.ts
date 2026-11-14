/** Apache-2.0 GenOffice f8c17004 annotations.ts: unchanged PageGeom/viewToPdf excerpt. */
/** Page geometry: unrotated PDF page size + total display rotation (base /Rotate + unsaved delta) */
export interface PageGeom {
  pw: number
  ph: number
  rot: number
  /** CropBox lower-left in PDF user space. */
  x0?: number
  y0?: number
  /** PDF /UserUnit; layout coordinates use this multiplier while PDF APIs use raw units. */
  userUnit?: number
}

const normRot = (r: number) => ((r % 360) + 360) % 360

/** Display size (scale=1; width/height swap with rotation) */
export function geomDispSize(g: PageGeom): { width: number; height: number } {
  return normRot(g.rot) % 180 === 0 ? { width: g.pw, height: g.ph } : { width: g.ph, height: g.pw }
}

/** Display coords (origin at page top-left, y down, scale=1) → PDF user space (y up) */
export function viewToPdf(g: PageGeom, vx: number, vy: number): [number, number] {
  const x0 = g.x0 ?? 0
  const y0 = g.y0 ?? 0
  const unit = g.userUnit ?? 1
  const pw = g.pw / unit
  const ph = g.ph / unit
  vx /= unit
  vy /= unit
  switch (normRot(g.rot)) {
    case 90:
      return [x0 + vy, y0 + vx]
    case 180:
      return [x0 + pw - vx, y0 + vy]
    case 270:
      return [x0 + pw - vy, y0 + ph - vx]
    default:
      return [x0 + vx, y0 + ph - vy]
  }
}

