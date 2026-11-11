import { expect, it, vi } from 'vitest'
const path = './workbook-zoom-selection'
async function product(): Promise<any> { return import(/* @vite-ignore */ path) }
const selection = { startRow: 1, endRow: 3, startColumn: 1, endColumn: 2 }
const skeleton = { rowHeightAccumulation: [20, 50, 50, 150], columnWidthAccumulation: [40, 90, 240], rowHeaderWidthAndMarginLeft: 40, columnHeaderHeightAndMarginTop: 20 }
function setup() {
  let zoom = 1
  const calls: any[] = [], sheet = { getSheetId: () => 'sheet', getZoom: () => zoom }
  let settle: () => void = () => {}
  const render = { with: () => ({ getCurrentSkeleton: () => skeleton }), engine: { width: 440, height: 280 } }
  const executeCommand = vi.fn((id: string, params: any) => {
    calls.push([id, params])
    return id === 'sheet.command.set-zoom-ratio' ? new Promise(resolve => { settle = () => { zoom = params.zoomRatio; resolve(true) } }) : Promise.resolve(true)
  })
  const core = {}
  const workbook = { getWorkbook: () => core, getId: () => 'book', getActiveSheet: () => sheet, getActiveRange: () => ({ getRange: () => selection }) }
  const runtime = { univer: { __getInjector: () => ({ get: () => ({ getRenderById: () => render }) }) }, univerAPI: {
    getActiveWorkbook: () => workbook, executeCommand,
  } }
  return { runtime, calls, settle: () => settle(), executeCommand }
}
it('fits actual unscaled cumulative geometry including hidden and nonuniform lines with Excel limits', async () => {
  const { selectionZoomRatio: ratio } = await product()
  expect(ratio(selection, skeleton, { width: 440, height: 280 })).toBe(2)
  expect(ratio({ ...selection, startRow: 0, startColumn: 0, endRow: 99, endColumn: 99 }, skeleton, { width: 440, height: 280 })).toBe(1.67)
  expect(ratio(selection, skeleton, { width: 10000, height: 10000 })).toBe(4)
  expect(ratio(selection, skeleton, { width: 41, height: 21 })).toBe(0.1)
  expect(ratio({ ...selection, startRow: 2, endRow: 2 }, skeleton, { width: 440, height: 280 })).toBeUndefined()
  expect(ratio(selection, skeleton, { width: 40, height: 280 })).toBeUndefined()
}, 15000)
it('awaits zoom before scrolling the unchanged selection to its top-left and emits current sheet identity', async () => {
  const { zoomWorkbookToSelection } = await product(), c = setup()
  const pending = zoomWorkbookToSelection(c.runtime)
  await Promise.resolve()
  expect(c.calls).toEqual([['sheet.command.set-zoom-ratio', { unitId: 'book', subUnitId: 'sheet', zoomRatio: 2 }]])
  c.settle()
  expect(await pending).toEqual({ changed: true, percent: 200, message: '缩放已调整为 200%，修改尚未保存。' })
  expect(c.calls[1]).toEqual(['sheet.command.scroll-to-cell', { range: selection, forceTop: true, forceLeft: true }])
})
it('does nothing for missing selection or renderer and never scrolls after rejected zoom', async () => {
  const { zoomWorkbookToSelection } = await product(), c = setup()
  expect((await zoomWorkbookToSelection({ univerAPI: { getActiveWorkbook: () => null } })).changed).toBe(false)
  const workbook = c.runtime.univerAPI.getActiveWorkbook()
  const original = c.runtime.univerAPI.getActiveWorkbook
  c.runtime.univerAPI.getActiveWorkbook = () => ({ ...workbook, getActiveRange: () => null }) as any
  expect((await zoomWorkbookToSelection(c.runtime)).changed).toBe(false)
  c.runtime.univerAPI.getActiveWorkbook = original
  const injector = c.runtime.univer.__getInjector
  c.runtime.univer.__getInjector = () => ({ get: () => ({ getRenderById: () => undefined }) }) as any
  expect((await zoomWorkbookToSelection(c.runtime)).changed).toBe(false)
  expect(c.calls).toEqual([])
  c.runtime.univer.__getInjector = injector
  c.executeCommand.mockImplementation(() => Promise.reject(new Error('zoom failed')))
  await expect(zoomWorkbookToSelection(c.runtime)).rejects.toThrow('zoom failed')
  expect(c.executeCommand).toHaveBeenCalledTimes(1)
})

it('rejects unapplied zoom but keeps an applied zoom when scroll returns a legal false no-op', async () => {
  const { zoomWorkbookToSelection } = await product()
  const c = setup(); c.executeCommand.mockImplementation(() => Promise.resolve(false))
  expect((await zoomWorkbookToSelection(c.runtime)).changed).toBe(false)
  expect(c.executeCommand).toHaveBeenCalledTimes(1)
  const d = setup(); const pending = zoomWorkbookToSelection(d.runtime)
  d.executeCommand.mockImplementation(() => Promise.resolve(false)); d.settle()
  expect((await pending).changed).toBe(true)
})
it.each(['sheet', 'workbook', 'disposed'])('cancels scrolling after async zoom when active identity becomes %s', async kind => {
  const { zoomWorkbookToSelection } = await product(), c = setup(), old = c.runtime.univerAPI.getActiveWorkbook()
  const pending = zoomWorkbookToSelection(c.runtime)
  c.runtime.univerAPI.getActiveWorkbook = (() => kind === 'disposed' ? null : kind === 'sheet'
    ? { ...old, getActiveSheet: () => ({ getSheetId: () => 'other' }) } : { ...old, getWorkbook: () => ({}) }) as any
  c.settle()
  expect((await pending).changed).toBe(kind === 'sheet')
  expect(c.executeCommand).toHaveBeenCalledTimes(1)
})
it('supports headless runtime without requesting an unavailable render service', async () => {
  const { zoomWorkbookToSelection } = await product(), c = setup(), get = vi.fn(() => { throw new Error('No provider') })
  c.runtime.univer.__getInjector = () => ({ has: () => false, get }) as any
  expect((await zoomWorkbookToSelection(c.runtime)).changed).toBe(false)
  expect(get).not.toHaveBeenCalled()
})

it('preserves observed zoom after a scroll exception with its concrete reason', async () => {
  const { zoomWorkbookToSelection } = await product(), c = setup()
  const pending = zoomWorkbookToSelection(c.runtime)
  c.executeCommand.mockImplementation(() => Promise.reject(new Error('renderer closed')))
  c.settle()
  expect(await pending).toMatchObject({changed:true,percent:200,message:expect.stringContaining('renderer closed')})
})
it('does not dirty a replacement workbook after the final scroll receipt resolves', async () => {
  const { zoomWorkbookToSelection } = await product(), c = setup(), old = c.runtime.univerAPI.getActiveWorkbook()
  let settleScroll: () => void = () => {}
  const pending = zoomWorkbookToSelection(c.runtime)
  c.executeCommand.mockImplementation(() => new Promise(resolve => { settleScroll = () => resolve(true) }))
  c.settle(); await Promise.resolve(); await Promise.resolve()
  c.runtime.univerAPI.getActiveWorkbook = () => ({ ...old, getWorkbook: () => ({}) })
  settleScroll()
  expect((await pending).changed).toBe(false)
}, 15000)

it('keeps observed zoom when zoom command applies then rejects', async () => {
  const { zoomWorkbookToSelection } = await product(), c = setup(), book = c.runtime.univerAPI.getActiveWorkbook()
  book.getActiveSheet().getZoom = () => 2
  c.executeCommand.mockImplementation(() => Promise.reject(new Error('receipt interrupted')))
  expect(await zoomWorkbookToSelection(c.runtime)).toMatchObject({changed:true,percent:200,message:expect.stringContaining('receipt interrupted')})
  expect(c.executeCommand).toHaveBeenCalledTimes(1)
}, 15000)
