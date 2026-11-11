import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('@univerjs/engine-render', () => ({ SheetExtension: class {}, SpreadsheetExtensionRegistry: { add: vi.fn() } }))
import { SpreadsheetExtensionRegistry } from '@univerjs/engine-render'
import { setSparklines } from './sparkline-render'
const bounds = { startX: 400, endX: 490, startY: 100, endY: 124 }
function draw(kind: 'column' | 'winLoss', values: number[], cell = bounds) {
  const Extension = vi.mocked(SpreadsheetExtensionRegistry.add).mock.calls[0]![0] as any
  setSparklines('bars', 'host', [{ kind, source: `A1:${values.length === 200 ? 'GR' : 'C'}1`, target: 'E4', showAxis: true }])
  const ctx = { save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), stroke: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), fillRect: vi.fn() }
  new Extension().draw(ctx, {}, { worksheet: { getUnitId: () => 'bars', getSheetId: () => 'host', getCell: (_r: number, c: number) => ({ v: values[c] }) }, getCellWithCoordByIndex: () => cell })
  return ctx
}
beforeEach(() => setSparklines('bars', 'host', undefined))
for (const kind of ['column', 'winLoss'] as const) {
  it.each([[1, -2, 3], [1, 2, 3], [-1, -2, -3], [0, 0, 0], [0, 1, -1], [-0.25, 0.25, 0], [2, 2, 2], [-2, -2, -2]])(`${kind}所有柱体保留真实宿主格内 %j`, (...values) => {
    const ctx = draw(kind, values)
    expect(ctx.fillRect).toHaveBeenCalledTimes(values.filter(value => value !== 0).length)
    for (const [x, y, width, height] of ctx.fillRect.mock.calls) {
      expect(x).toBeGreaterThanOrEqual(bounds.startX + 2)
      expect(x + width).toBeLessThanOrEqual(bounds.endX - 2 + 1e-9)
      expect(y).toBeGreaterThanOrEqual(bounds.startY + 2)
      expect(y + height).toBeLessThanOrEqual(bounds.endY - 2 + 1e-9)
      expect(width).toBeGreaterThan(0)
      expect(height).toBeGreaterThan(0)
    }
  })
}
it('柱形以零为基准保持正负值幅度，盈亏图每条仅使用半高且不依赖幅度', () => {
  const column = draw('column', [-2, 8, 1])
  expect((window as any).__sheetsWebSparklines.targetBounds.get('bars::host::E4')).toEqual(bounds)
  expect(column.moveTo).toHaveBeenCalledWith(402, 118)
  expect(column.lineTo).toHaveBeenCalledWith(488, 118)
  expect(column.fillRect.mock.calls.map(([, y, , h]) => [y, h])).toEqual([[118, 4], [102, 16], [116, 2]])
  const winLoss = draw('winLoss', [-0.25, 8, 0])
  expect(winLoss.fillRect.mock.calls.map(([, y, , h]) => [y, h])).toEqual([[112, 10], [102, 10]])
})
it('极小宿主没有可画空间时跳过；密集柱不强制一像素宽造成越格', () => {
  for (const cell of [{ ...bounds, endX: bounds.startX + 4 }, { ...bounds, endY: bounds.startY + 3 }]) {
    expect(draw('column', [1, 2, 3], cell).fillRect).not.toHaveBeenCalled()
    expect(draw('winLoss', [1, -2, 3], cell).fillRect).not.toHaveBeenCalled()
  }
  const ctx = draw('column', Array.from({ length: 200 }, () => 1))
  for (const [x, , width] of ctx.fillRect.mock.calls) expect(x + width).toBeLessThanOrEqual(bounds.endX - 2 + 1e-9)
})
