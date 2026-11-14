import { expect, it } from 'vitest'
import { chartObjectAnchor, chartResizeCorners, chartResizeHandleAt, chartResizeHandles } from './workbook-chart-object-geometry'
import { chartAtPoint, chartBounds } from './workbook-chart-geometry'

const anchor = { fromRow: 1, fromColumn: 1, fromRowOffset: 0, fromColumnOffset: 0, toRow: 4, toColumn: 4, toRowOffset: 0, toColumnOffset: 0 }
const grid = { columnWidth: (index: number) => index === 2 ? 60 : 40, rowHeight: () => 20, scaleX: 2, scaleY: 2, rtl: false }
it('moves with real variable column widths, zoom and EMU offsets', () => {
  expect(chartObjectAnchor(anchor, 'move', 'se', 130, 50, grid)).toEqual({
    fromRow: 2, fromColumn: 2, fromRowOffset: 5 * 9525, fromColumnOffset: 25 * 9525,
    toRow: 5, toColumn: 5, toRowOffset: 5 * 9525, toColumnOffset: 25 * 9525,
  })
})
it('clamps movement to the sheet start without shrinking either dimension', () => {
  expect(chartObjectAnchor(anchor, 'move', 'se', -1000, -1000, grid)).toEqual({
    fromRow: 0, fromColumn: 0, fromRowOffset: 0, fromColumnOffset: 0,
    toRow: 3, toColumn: 3, toRowOffset: 0, toColumnOffset: 0,
  })
})
it('clamps movement to the real final worksheet cell without shrinking the frame', () => {
  const source = { ...anchor, fromRow: 1048570, toRow: 1048574, fromColumn: 16380, toColumn: 16383 }
  expect(chartObjectAnchor(source, 'move', 'se', 1000, 1000, { ...grid, scaleX: 1, scaleY: 1 })).toEqual({
    ...source, fromRow: 1048572, toRow: 1048575, toRowOffset: 20 * 9525, fromColumn: 16381, toColumnOffset: 40 * 9525,
  })
})
it.each(chartResizeCorners)('resizes only the %s edges while retaining the opposite edges', corner => {
  const next = chartObjectAnchor(anchor, 'resize', corner, 20, 10, { ...grid, scaleX: 1, scaleY: 1 })
  expect(next.fromColumnOffset).toBe(corner.includes('w') ? 20 * 9525 : 0)
  expect(next.toColumnOffset).toBe(corner.includes('e') ? 20 * 9525 : 0)
  expect(next.fromRowOffset).toBe(corner.includes('n') ? 10 * 9525 : 0)
  expect(next.toRowOffset).toBe(corner.includes('s') ? 10 * 9525 : 0)
})
it('enforces the source 24px minimum frame and mirrors horizontal movement and resize edges in RTL', () => {
  const smallest = chartObjectAnchor(anchor, 'resize', 'nw', 1000, 1000, grid)
  expect(smallest).toEqual({ ...anchor, fromRow: 2, fromRowOffset: 16 * 9525, fromColumn: 3, fromColumnOffset: 16 * 9525 })
  const rtl = chartObjectAnchor(anchor, 'resize', 'e', 20, 0, { ...grid, scaleX: 1, scaleY: 1, rtl: true })
  expect(rtl).toEqual({ ...anchor, fromColumn: 0, fromColumnOffset: 20 * 9525 })
})
it('walks synthetic one-cell ext offsets across real grid cells and leaves zero-size hidden rows finite', () => {
  const source = { ...anchor, toColumn: 1, toRow: 1, toColumnOffset: 140 * 9525, toRowOffset: 60 * 9525 }
  expect(chartObjectAnchor(source, 'move', 'se', 0, 0, grid)).toEqual(anchor)
  const hidden = chartObjectAnchor(anchor, 'move', 'se', 40, 20, { ...grid, columnWidth: () => 0, rowHeight: () => 0 })
  expect(Object.values(hidden).every(Number.isFinite)).toBe(true)
})
it('hits all eight screen-sized handles at the exact shared chart bounds', () => {
  const bounds = { x0: 40, y0: 20, x1: 180, y1: 80 }
  expect(chartResizeHandles(bounds)).toEqual([
    { corner: 'nw', x: 40, y: 20 }, { corner: 'n', x: 110, y: 20 }, { corner: 'ne', x: 180, y: 20 }, { corner: 'e', x: 180, y: 50 },
    { corner: 'se', x: 180, y: 80 }, { corner: 's', x: 110, y: 80 }, { corner: 'sw', x: 40, y: 80 }, { corner: 'w', x: 40, y: 50 },
  ])
  for (const handle of chartResizeHandles(bounds)) expect(chartResizeHandleAt(bounds, handle.x + 2, handle.y + 2, 2, 2)).toBe(handle.corner)
  expect(chartResizeHandleAt(bounds, 100, 40, 2, 2)).toBeUndefined()
})
it('shares mirrored RTL source markers with painting and hits the exact 24px minimum frame', () => {
  const cell = (row: number, column: number) => ({ startX: 500 - (column + 1) * 40, endX: 500 - column * 40, startY: row * 20 })
  expect(chartBounds({ ...anchor, fromColumnOffset: 5 * 9525, toColumnOffset: 10 * 9525 }, cell, true)).toEqual({ x0: 330, x1: 455, y0: 20, y1: 80 })
  const tiny = { chartPath: 'tiny', kind: 'column' as const, series: [{ valuesRef: 'A1' }], anchor: { fromRow: 0, fromColumn: 0, toRow: 0, toColumn: 0, toColumnOffset: 24 * 9525, toRowOffset: 24 * 9525 } }
  const ltrCell = () => ({ startX: 0, startY: 0 })
  expect(chartAtPoint([tiny], { x: 12, y: 12 }, ltrCell)?.chartPath).toBe('tiny')
  expect(chartAtPoint([{ ...tiny, anchor: { ...tiny.anchor, toColumnOffset: 23 * 9525 } }], { x: 12, y: 12 }, ltrCell)).toBeUndefined()
})
