// 固定源 outline-model.ts：分组边栏间距与层级坐标。
export const OUTLINE_LEVEL_STEP = 13
export const OUTLINE_GUTTER_PAD = 3
export function outlineMaxLevel(entries: ReadonlyMap<number, { level: number }>): number {
  let max = 0
  for (const entry of entries.values()) max = Math.max(max, entry.level)
  return Math.min(7, max)
}
export const outlineGutterThickness = (max: number): number => max === 0 ? 0 : (max + 1) * OUTLINE_LEVEL_STEP + OUTLINE_GUTTER_PAD * 2
export const outlineColumnCenter = (level: number): number => OUTLINE_GUTTER_PAD + (level - 1) * OUTLINE_LEVEL_STEP + OUTLINE_LEVEL_STEP / 2
