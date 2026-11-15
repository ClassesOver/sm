// GenOffice Shape Format → Outline presets (DrawingML prstDash values).
export const OUTLINE_DASHES = ['solid', 'dash', 'sysDot', 'dashDot'] as const
export type OutlineDash = typeof OUTLINE_DASHES[number]
export type ShapeStroke = { color: string; widthPt: number; dash?: OutlineDash }

export function isOutlineDash(value: unknown): value is OutlineDash {
  return OUTLINE_DASHES.some(dash => dash === value)
}
