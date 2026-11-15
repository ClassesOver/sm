export type ShapeGradient = {
  from: string
  to: string
  angleDeg: 0 | 45 | 90
  radial: boolean
}
export type ShapeFill = string | ShapeGradient

const hex = (value: unknown): value is string => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)

export function isShapeGradient(value: unknown): value is ShapeGradient {
  if (!value || typeof value !== 'object') return false
  const item = value as ShapeGradient
  return Object.keys(item).sort().join() === 'angleDeg,from,radial,to' &&
    hex(item.from) && hex(item.to) && typeof item.radial === 'boolean' &&
    (item.radial ? item.angleDeg === 0 : [0, 45, 90].includes(item.angleDeg))
}

export function isShapeFill(value: unknown): value is ShapeFill {
  return value === 'none' || hex(value) || isShapeGradient(value)
}

export function shapeFillPatch(fill: ShapeFill) {
  return typeof fill === 'string' ? fill : {
    stops: [{ pos: 0, color: fill.from }, { pos: 1, color: fill.to }],
    ...(fill.radial ? { radial: true } : { angle: fill.angleDeg * 60000 }),
  }
}
