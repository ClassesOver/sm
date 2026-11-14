import { afterEach, expect, it, vi } from 'vitest'
import { IRenderManagerService, SHEET_VIEWPORT_KEY } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import type { UniverRuntime } from './workbook-vendor/grid/create-univer'
import { installWorkbookChartObjectInteraction } from './workbook-chart-object-interaction'
import {installWorkbookChartSelection} from './workbook-chart-selection'
import {setChartElementRegions} from './workbook-chart-element-hit'

const disposables: { dispose(): void }[] = []
afterEach(() => { disposables.splice(0).forEach(value => value.dispose()); document.body.replaceChildren() })
function harness(kind: ChartReadSpec['anchorKind'] = 'twoCellAnchor',withSelection=false) {
  const root = document.createElement('div'), canvas = document.createElement('canvas'); root.append(canvas); document.body.append(root)
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 800, height: 500 } as DOMRect)
  const anchor = { fromRow: 6, fromColumn: 6, toRow: 10, toColumn: 10, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 }
  const charts: ChartReadSpec[] = [{ chartPath: 'xl/charts/chart1.xml', kind: 'column', anchor: { fromRow: 1, fromColumn: 1, toRow: 4, toColumn: 4 }, series: [{ valuesRef: 'A1' }] },
    { chartPath: 'xl/charts/chart2.xml', kind: 'column', anchorKind: kind, anchor, series: [{ valuesRef: 'A1' }] }]
  let sheetCore = {}, available = true, selected = 'xl/charts/chart2.xml'
  const sheet = { getSheetName: () => 'Sheet', getSheetId: () => 'sheet', getSheet: () => sheetCore,
    getColumnWidth: () => 40, getRowHeight: () => 20, getMaxColumns: () => 20, getMaxRows: () => 30 }
  Object.assign(sheetCore, { getConfig: () => ({ rightToLeft: 0, defaultColumnWidth: 40, defaultRowHeight: 20 }) })
  const book = { getId: () => 'book', getWorkbook: () => book, getActiveSheet: () => sheet }
  const scene = { getAncestorScale: () => ({ scaleX: 1, scaleY: 1 }), getActiveViewportByCoord: () => ({ viewportKey: SHEET_VIEWPORT_KEY.VIEW_MAIN }),
    getCoordRelativeToViewport: (point: unknown) => point, getScrollXYInfoByViewport: () => ({ x: 0, y: 0 }) }
  const skeleton = { rowHeaderWidthAndMarginLeft: 0, columnHeaderHeightAndMarginTop: 0,
    getCellWithCoordByIndex: (row: number, column: number) => {
      if (row >= 30 || column >= 20) throw Error('outside the data-sized grid')
      return { startX: column * 40, startY: row * 20, endX: (column + 1) * 40 }
    } }
  const render = { scene, engine: { getCanvasElement: () => canvas }, with: (key: unknown) => key === SheetSkeletonManagerService ? { getCurrentSkeleton: () => skeleton } : undefined }
  const runtime = { univer: { __getInjector: () => ({ has: () => true, get: (key: unknown) => key === IRenderManagerService ? { getRenderById: () => render } : undefined }) },
    univerAPI: { getActiveWorkbook: () => book } } as unknown as UniverRuntime
  const edits: { target: { path: string; core: object }; mode: string; anchor: typeof anchor }[] = [], errors: string[] = []
  const selectElementAt=vi.fn()
  const selection=withSelection?installWorkbookChartSelection(root,runtime,{charts:()=>charts,available:()=>available,changed:()=>{},remove:()=>{}}):undefined
  if(selection){disposables.push(selection);setChartElementRegions('book','sheet',charts[1]!,[{element:{kind:'point',seriesIndex:0,pointIndex:2},contains:(x,y)=>x===300&&y===150}])}
  const handle = installWorkbookChartObjectInteraction(root, runtime, {
    charts: () => charts, current: () => ({ sheetName: 'Sheet', chartPath: selected }), select: target => { selected = target.chartPath; return selection?.select(target)??true }, available: () => available,
    capture: chart => ({ path: chart.chartPath, core: sheetCore }), validate: target => { if (!available || target.core !== sheetCore) throw Error('图表目标已变化或受保护') },
    commit: async (target, mode, anchor) => { edits.push({ target, mode, anchor }) }, error: message => errors.push(message),selectElementAt:(target,x,y)=>{selectElementAt(target,x,y);selection?.selectElementAt(target,x,y)},
  })
  disposables.push(handle)
  const pointer = (type: string, x = 300, y = 150, id = 1, target: EventTarget = canvas) => {
    const event = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true, cancelable: true })
    Object.defineProperty(event, 'pointerId', { value: id }); target.dispatchEvent(event); return event
  }
  return { root, canvas, anchor, edits, errors, pointer,selectElementAt,selection, selected: () => selected, protected: () => { available = false }, replace: () => { sheetCore = {} } }
}
it('delegates element selection from the owning window capture handler before swallowing the real canvas gesture',()=>{const h=harness(),rootPointer=vi.fn();h.root.addEventListener('pointerdown',rootPointer,true);h.pointer('pointerdown');h.pointer('pointerup');expect(rootPointer).not.toHaveBeenCalled();expect(h.selectElementAt).toHaveBeenCalledExactlyOnceWith({sheetName:'Sheet',chartPath:'xl/charts/chart2.xml'},300,150);expect(h.edits).toEqual([])})
it('two actual capture gestures narrow the same series to sparse point index 2 without adding history or interfering with resize',()=>{const h=harness('twoCellAnchor',true);h.pointer('pointerdown');h.pointer('pointerup');h.pointer('click');expect(h.selection!.element()).toEqual({kind:'series',seriesIndex:0});h.pointer('pointerdown');h.pointer('pointerup');h.pointer('click');expect(h.selection!.element()).toEqual({kind:'point',seriesIndex:0,pointIndex:2});expect(h.selectElementAt).toHaveBeenCalledTimes(2);expect(h.edits).toEqual([]);h.pointer('pointerdown',10,10);h.pointer('pointerup',10,10);h.pointer('click',10,10);expect(h.selection!.current()).toBeUndefined();h.pointer('pointerdown');h.pointer('pointerup');h.pointer('click');expect(h.selection!.element()).toEqual({kind:'series',seriesIndex:0});h.selectElementAt.mockClear();h.pointer('pointerdown',400,200);h.pointer('pointerup',400,200);expect(h.selectElementAt).not.toHaveBeenCalled();h.protected();h.pointer('pointerdown');expect(h.selectElementAt).not.toHaveBeenCalled()})
it('moves the exact selected chart with a transient preview and commits only on pointer release', async () => {
  const h = harness(), native = vi.fn(); h.canvas.addEventListener('pointerdown', native)
  expect(h.pointer('pointerdown').defaultPrevented).toBe(true)
  h.pointer('pointermove', 340, 170)
  expect(document.querySelector('[data-chart-geometry-preview]')).not.toBeNull()
  expect(h.edits).toEqual([])
  h.pointer('pointerup', 340, 170)
  await vi.waitFor(() => expect(h.edits).toHaveLength(1))
  expect(h.edits[0]).toMatchObject({ target: { path: 'xl/charts/chart2.xml' }, mode: 'move', anchor: { ...h.anchor, fromColumn: 7, toColumn: 11, fromRow: 7, toRow: 11 } })
  expect(document.querySelector('[data-chart-geometry-preview]')).toBeNull()
  expect(native).not.toHaveBeenCalled()
})
it('resizes by the selected southeast handle rather than treating it as a move', async () => {
  const h = harness(); h.pointer('pointerdown', 400, 200); h.pointer('pointerup', 480, 240)
  await vi.waitFor(() => expect(h.edits).toHaveLength(1))
  expect(h.edits[0]).toMatchObject({ mode: 'resize', anchor: { ...h.anchor, toColumn: 12, toRow: 12 } })
})
it('previews and commits a free move beyond the initially data-sized grid using its actual default sizes', async () => {
  const h = harness(); h.pointer('pointerdown'); h.pointer('pointermove', 1300, 1150)
  const preview = document.querySelector<HTMLElement>('[data-chart-geometry-preview]')
  expect(preview).not.toBeNull()
  expect(preview!.style.left).toBe('1240px'); expect(preview!.style.top).toBe('1120px')
  h.pointer('pointerup', 1300, 1150)
  await vi.waitFor(() => expect(h.edits).toHaveLength(1))
  expect(h.edits[0]!.anchor).toMatchObject({ fromRow: 56, toRow: 60, fromColumn: 31, toColumn: 35 })
})
it.each(['Escape', 'pointercancel', 'blur', 'wheel'])('cancels a preview on %s without adding an operation', action => {
  const h = harness(); h.pointer('pointerdown'); h.pointer('pointermove', 340, 170)
  if (action === 'Escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  else if (action === 'pointercancel') h.pointer(action)
  else window.dispatchEvent(new Event(action))
  h.pointer('pointerup', 340, 170)
  expect(h.edits).toEqual([]); expect(document.querySelector('[data-chart-geometry-preview]')).toBeNull()
})
it('keeps the accepted pointerup out of native cell double-click synthesis after Escape cancels the geometry', () => {
  const h = harness(), nativeUp = vi.fn(); h.canvas.addEventListener('pointerup', nativeUp)
  h.pointer('pointerdown'); h.pointer('pointermove', 340, 170)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(h.pointer('pointerup', 340, 170).defaultPrevented).toBe(true)
  expect(nativeUp).not.toHaveBeenCalled(); expect(h.edits).toEqual([])
})
it.each(['protected', 'replace'] as const)('rechecks target identity on release when %s changes during a gesture', action => {
  const h = harness(); h.pointer('pointerdown'); h[action](); h.pointer('pointerup', 340, 170)
  expect(h.edits).toEqual([]); expect(h.errors[0]).toContain('图表目标已变化')
})
it('ignores foreign pointers and does not capture a cell drag ending over a chart', async () => {
  const h = harness()
  expect(h.pointer('pointerdown', 10, 10).defaultPrevented).toBe(false)
  expect(h.pointer('pointerup').defaultPrevented).toBe(false)
  h.pointer('pointerdown'); h.pointer('pointerup', 340, 170, 2)
  expect(h.edits).toEqual([])
  h.pointer('pointerup', 340, 170)
  await vi.waitFor(() => expect(h.edits).toHaveLength(1))
})
it('leaves simple selection clicks out of history and retains the absolute-anchor limitation', () => {
  const h = harness(); h.pointer('pointerdown'); h.pointer('pointerup'); expect(h.edits).toEqual([])
  const absolute = harness('absoluteAnchor'); absolute.pointer('pointerdown'); absolute.pointer('pointerup', 340, 170)
  expect(absolute.edits).toEqual([]); expect(absolute.errors[0]).toContain('绝对锚点')
})
