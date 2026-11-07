/** OOXML uses 91..180 for clockwise angles; Univer uses signed degrees. */
export function ooxmlRotationToUniver(rotation: number): { a: number; v?: number } | undefined {
  if (rotation === 255) return { a: 0, v: 1 }
  if (!Number.isInteger(rotation) || rotation < 0 || rotation > 180) return undefined
  return { a: rotation <= 90 ? rotation : 90 - rotation }
}
export function univerRotationToOoxml(rotation?: { a?: number; v?: number } | null): number | undefined {
  if (!rotation) return undefined
  if (rotation.v === 1) return 255
  const angle = rotation.a ?? 0
  if (!Number.isInteger(angle) || angle < -90 || angle > 90) return undefined
  return angle < 0 ? 90 - angle : angle
}
export const ROTATION_VALUES = { 'rotate:45': 45, 'rotate:-45': -45, 'rotate:vertical': 'v', 'rotate:90': 90, 'rotate:-90': -90, 'rotate:0': 0 } as const
export type RotationValue = typeof ROTATION_VALUES[keyof typeof ROTATION_VALUES]
