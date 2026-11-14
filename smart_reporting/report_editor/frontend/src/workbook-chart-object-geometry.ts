import type { DrawingAnchor } from '@sheets-web/xlsx-engine'
import type { ChartBounds } from './workbook-chart-geometry'

export const chartResizeCorners = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'] as const
export type ChartResizeCorner = typeof chartResizeCorners[number]
export interface ChartObjectGrid {
  columnWidth(index: number): number
  rowHeight(index: number): number
  scaleX: number
  scaleY: number
  rtl: boolean
}
export function chartResizeHandles(bounds: ChartBounds): { corner: ChartResizeCorner; x: number; y: number }[] {
  return chartResizeCorners.map(corner => ({ corner,
    x: corner.includes('w') ? bounds.x0 : corner.includes('e') ? bounds.x1 : (bounds.x0 + bounds.x1) / 2,
    y: corner.includes('n') ? bounds.y0 : corner.includes('s') ? bounds.y1 : (bounds.y0 + bounds.y1) / 2,
  }))
}
export function chartResizeHandleAt(bounds: ChartBounds, x: number, y: number, scaleX: number, scaleY: number): ChartResizeCorner | undefined {
  return chartResizeHandles(bounds).find(point => Math.abs(x - point.x) <= 5 / scaleX && Math.abs(y - point.y) <= 5 / scaleY)?.corner
}

// 移植固定源 WorkbookVisuals.tsx 的 markerFrom/walkMarker/markerSpan 与提交几何。
interface Marker { index: number; offset: number }
const marker = (index: number, offset: number): Marker => ({ index, offset: offset / 9525 })
function walk(from: Marker, delta: number, size: (index: number) => number, max: number): Marker {
  let index = Math.min(from.index, max), offset = from.offset + delta
  while (offset < 0 && index > 0) { index--; offset += size(index) }
  if (offset < 0) offset = 0
  while (index < max && offset >= size(index)) { offset -= size(index); index++ }
  if (index >= max) offset = Math.min(offset, size(max))
  return { index, offset }
}
function span(from: Marker, to: Marker, size: (index: number) => number): number {
  let cells = 0
  for (let index = Math.min(from.index, to.index); index < Math.max(from.index, to.index); index++) cells += size(index)
  return to.offset - from.offset + (from.index <= to.index ? cells : -cells)
}
export function chartObjectAnchor(anchor: DrawingAnchor, mode: 'move' | 'resize', corner: ChartResizeCorner, dx: number, dy: number, grid: ChartObjectGrid): DrawingAnchor {
  const width = (index: number) => Math.max(1, grid.columnWidth(index)), height = (index: number) => Math.max(1, grid.rowHeight(index))
  let fromX = marker(anchor.fromColumn, anchor.fromColumnOffset), fromY = marker(anchor.fromRow, anchor.fromRowOffset)
  let toX = marker(anchor.toColumn, anchor.toColumnOffset), toY = marker(anchor.toRow, anchor.toRowOffset)
  dx = (grid.rtl ? -dx : dx) / grid.scaleX; dy /= grid.scaleY
  if (grid.rtl) corner = corner.replace(/[ew]/g, edge => edge === 'e' ? 'w' : 'e') as ChartResizeCorner
  if (mode === 'move') {
    const shift = (delta: number, from: Marker, to: Marker, size: (index: number) => number, max: number) => {
      const leading = delta > 0 ? to : from
      return span(leading, walk(leading, delta, size, max), size)
    }
    const x = shift(dx, fromX, toX, width, 16383), y = shift(dy, fromY, toY, height, 1048575)
    fromX = walk(fromX, x, width, 16383); toX = walk(toX, x, width, 16383)
    fromY = walk(fromY, y, height, 1048575); toY = walk(toY, y, height, 1048575)
  } else {
    if (corner.includes('e')) { toX = walk(toX, dx, width, 16383); if (span(fromX, toX, width) < 24) toX = walk(fromX, 24, width, 16383) }
    if (corner.includes('w')) { fromX = walk(fromX, dx, width, 16383); if (span(fromX, toX, width) < 24) fromX = walk(toX, -24, width, 16383) }
    if (corner.includes('s')) { toY = walk(toY, dy, height, 1048575); if (span(fromY, toY, height) < 24) toY = walk(fromY, 24, height, 1048575) }
    if (corner.includes('n')) { fromY = walk(fromY, dy, height, 1048575); if (span(fromY, toY, height) < 24) fromY = walk(toY, -24, height, 1048575) }
  }
  return { fromRow: fromY.index, fromColumn: fromX.index, fromRowOffset: Math.round(fromY.offset * 9525), fromColumnOffset: Math.round(fromX.offset * 9525),
    toRow: toY.index, toColumn: toX.index, toRowOffset: Math.round(toY.offset * 9525), toColumnOffset: Math.round(toX.offset * 9525) }
}
