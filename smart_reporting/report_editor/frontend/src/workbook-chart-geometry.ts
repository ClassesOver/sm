import type { ChartReadSpec } from '@sheets-web/xlsx-engine'

export interface ChartBounds { x0: number; y0: number; x1: number; y1: number }
export type ChartCellAt = (row: number, column: number) => { startX: number; startY: number; endX?: number }

export function chartBounds(anchor: ChartReadSpec['anchor'], cellAt: ChartCellAt, rtl = false): ChartBounds {
  const from = cellAt(anchor.fromRow, anchor.fromColumn), to = cellAt(anchor.toRow, anchor.toColumn)
  const x0 = (rtl ? from.endX ?? from.startX : from.startX) + (rtl ? -1 : 1) * (anchor.fromColumnOffset ?? 0) / 9525, y0 = from.startY + (anchor.fromRowOffset ?? 0) / 9525
  const x1 = (rtl ? to.endX ?? to.startX : to.startX) + (rtl ? -1 : 1) * (anchor.toColumnOffset ?? 0) / 9525, y1 = to.startY + (anchor.toRowOffset ?? 0) / 9525
  return { x0: Math.min(x0, x1), y0: Math.min(y0, y1), x1: Math.max(x0, x1), y1: Math.max(y0, y1) }
}

export function chartAtPoint(charts: readonly ChartReadSpec[], point: { x: number; y: number }, cellAt: ChartCellAt, rtl = false): ChartReadSpec | undefined {
  for (const chart of [...charts].reverse()) {
    try {
      const { x0, y0, x1, y1 } = chartBounds(chart.anchor, cellAt, rtl)
      if (x1-x0 >= 24 && y1-y0 >= 24 && point.x >= x0 && point.x <= x1 && point.y >= y0 && point.y <= y1) return chart
    } catch { /* 和绘制路径一致，忽略无法取得几何的来源。 */ }
  }
  return undefined
}
