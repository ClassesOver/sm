import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('@univerjs/engine-render', () => ({ SheetExtension: class {}, SpreadsheetExtensionRegistry: { add: vi.fn() } }))
import { SpreadsheetExtensionRegistry } from '@univerjs/engine-render'
import { setSparklines, setSparklineWorkbookResolver } from './sparkline-render'
const source = (values: number[]) => ({ getCell: vi.fn((_r: number, c: number) => ({ v: values[c] })) })
const draw = () => {
  const Extension = vi.mocked(SpreadsheetExtensionRegistry.add).mock.calls[0]![0] as any
  const ctx = { save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), stroke: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), fillRect: vi.fn() }
  const host = { ...source([1, -2, 3]), getUnitId: () => 'unit', getSheetId: () => 'host' }
  new Extension().draw(ctx, {}, { worksheet: host, getCellWithCoordByIndex: () => ({ startX: 0, endX: 100, startY: 0, endY: 100 }) })
  return { ctx, host }
}
beforeEach(() => {
  setSparklines('unit', 'host', undefined)
  setSparklineWorkbookResolver('unit', undefined)
  setSparklineWorkbookResolver('other-unit', undefined)
})
it('真正读取当前unit内的跨表worksheet，绘制来源数值路径而非宿主页数值', () => {
  const other = source([-2, 8, 1]), resolver = vi.fn(name => name === "来源 ! O'Brien 中文" ? other : undefined)
  setSparklineWorkbookResolver('unit', resolver)
  setSparklines('unit', 'host', [{ kind: 'line', source: 'A1:C1', sourceSheet: "来源 ! O'Brien 中文", target: 'D1' }])
  const { ctx, host } = draw()
  expect(resolver).toHaveBeenCalledWith("来源 ! O'Brien 中文")
  expect(other.getCell).toHaveBeenCalledTimes(3)
  expect(host.getCell).not.toHaveBeenCalled()
  expect(ctx.moveTo).toHaveBeenCalledWith(2, 98)
  expect(ctx.lineTo.mock.calls).toEqual([[50, 2], [98, 69.2]])
})
it('来源未限定时读取宿主；限定来源缺失或仅其它unit有resolver时跳过', () => {
  setSparklines('unit', 'host', [{ kind: 'line', source: 'A1:C1', target: 'D1' }])
  expect(draw().ctx.stroke).toHaveBeenCalledOnce()
  setSparklines('unit', 'host', [{ kind: 'line', source: 'A1:C1', sourceSheet: 'Missing', target: 'D1' }])
  setSparklineWorkbookResolver('other-unit', () => source([-2, 8, 1]))
  const missing = draw()
  expect(missing.ctx.stroke).not.toHaveBeenCalled()
  expect(missing.host.getCell).not.toHaveBeenCalled()
  expect((window as any).__sheetsWebSparklines.lastSkip).toContain('Missing')
})
it('跨表值实时更新且同名来源可以由稳定身份resolver跨改名解析', () => {
  const values = [-2, 8, 1], sheet = source(values)
  setSparklineWorkbookResolver('unit', name => name === 'Old Name' ? sheet : undefined)
  setSparklines('unit', 'host', [{ kind: 'line', source: 'A1:C1', sourceSheet: 'Old Name', target: 'D1' }])
  const first = draw().ctx.lineTo.mock.calls
  values[2] = 8
  const second = draw().ctx.lineTo.mock.calls
  expect(first).not.toEqual(second)
  expect(second[1]).toEqual([98, 2])
})
