// Fixed source f8c17004fb730df11f0f743164ffd8b4281bb38c table-sizing.ts pure fit closure.
export const MIN_TABLE_COLUMN_PX = 40

function finiteWidth(value: unknown, fallback: number): number {
  const width = Number(value)
  return Number.isFinite(width) && width > 0 ? width : fallback
}

/**
 * Fit a table grid into the section content box. Requested columns keep their
 * requested size where possible; unselected columns give up space first.
 */
export function fitColumnWidths(
  current: number[],
  requested: ReadonlyMap<number, number>,
  maxWidth: number,
  minimum = MIN_TABLE_COLUMN_PX,
): number[] {
  if (current.length === 0) return []
  const limit = Math.max(1, finiteWidth(maxWidth, 1))
  const floor = Math.min(Math.max(1, minimum), limit / current.length)
  const widths = current.map((width, index) =>
    Math.max(floor, finiteWidth(requested.get(index), finiteWidth(width, floor))),
  )

  let excess = widths.reduce((sum, width) => sum + width, 0) - limit
  const shrink = (indexes: number[]) => {
    if (excess <= 0.01 || indexes.length === 0) return
    const capacity = indexes.reduce((sum, index) => sum + Math.max(0, widths[index] - floor), 0)
    if (capacity <= 0.01) return
    const take = Math.min(excess, capacity)
    for (const index of indexes) {
      const available = Math.max(0, widths[index] - floor)
      widths[index] -= take * (available / capacity)
    }
    excess -= take
  }

  const untouched = widths.map((_, index) => index).filter((index) => !requested.has(index))
  const changed = widths.map((_, index) => index).filter((index) => requested.has(index))
  shrink(untouched)
  shrink(changed)

  // Floating point drift must never write an oversized OOXML grid.
  const total = widths.reduce((sum, width) => sum + width, 0)
  if (total > limit)
    widths[widths.length - 1] = Math.max(floor, widths[widths.length - 1] - (total - limit))
  const rounded = widths.map((width) => Math.max(1, Math.round(width * 100) / 100))
  const roundedTotal = rounded.reduce((sum, width) => sum + width, 0)
  if (roundedTotal > limit) {
    rounded[rounded.length - 1] = Math.max(
      1,
      Math.round((rounded[rounded.length - 1] - (roundedTotal - limit)) * 100) / 100,
    )
  }
  return rounded
}

