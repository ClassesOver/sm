import { afterEach, expect, it, vi } from 'vitest'
import { IRenderManagerService, SHEET_VIEWPORT_KEY } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import { installWorkbookChartSelection, selectedChartPath } from './workbook-chart-selection'
import type { UniverRuntime } from './workbook-vendor/grid/create-univer'
import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { chartAtPoint, chartBounds } from './workbook-chart-geometry'
import {setChartElementRegions} from './workbook-chart-element-hit'

const cellAt = (row: number, column: number) => ({ startX: column * 40, startY: row * 20 })
const chart = (chartPath: string, anchor: ChartReadSpec['anchor'] = { fromRow: 1, fromColumn: 2, toRow: 5, toColumn: 6 }): ChartReadSpec => ({ chartPath, kind: 'column', anchor, title: 'Same', series: [{ valuesRef: 'A1:A2' }] })

it('命中同名图表的真实路径而不是取第一图', () => {
  const first = chart('xl/charts/chart1.xml')
  const second = chart('xl/charts/chart2.xml', { fromRow: 6, fromColumn: 7, toRow: 10, toColumn: 11 })
  expect(chartAtPoint([first, second], { x: 300, y: 160 }, cellAt)?.chartPath).toBe('xl/charts/chart2.xml')
  expect(chartAtPoint([first, second], { x: 100, y: 30 }, cellAt)?.chartPath).toBe('xl/charts/chart1.xml')
})
it('重叠图表遵循画布的末项在上绘制顺序', () => {
  expect(chartAtPoint([chart('one'), chart('two')], { x: 100, y: 30 }, cellAt)?.chartPath).toBe('two')
})
it('绘图边界包含精确EMU偏移而不是整格近似', () => {
  const spec = chart('one', { fromRow: 1, fromColumn: 2, toRow: 1, toColumn: 2, fromRowOffset: 3*9525, fromColumnOffset: 5*9525, toRowOffset: 63*9525, toColumnOffset: 75*9525 })
  expect(chartBounds(spec.anchor, cellAt)).toEqual({ x0: 85, y0: 23, x1: 155, y1: 83 })
  expect(chartAtPoint([spec], { x: 84, y: 24 }, cellAt)).toBeUndefined()
  expect(chartAtPoint([spec], { x: 86, y: 24 }, cellAt)?.chartPath).toBe('one')
})
it('反向坐标与负偏移和实际渲染使用相同几何', () => {
  expect(chartBounds({ fromRow: 5, fromColumn: 6, toRow: 1, toColumn: 2, fromRowOffset: -9525, toColumnOffset: -2*9525 }, cellAt)).toEqual({ x0: 78, y0: 20, x1: 240, y1: 99 })
})
it('空白网格、未绘制的小图和无法解析的锚点不产生目标', () => {
  expect(chartAtPoint([chart('one')], { x: 20, y: 30 }, cellAt)).toBeUndefined()
  expect(chartAtPoint([chart('tiny', { fromRow: 0, fromColumn: 0, toRow: 1, toColumn: 0 })], { x: 0, y: 1 }, cellAt)).toBeUndefined()
  expect(chartAtPoint([chart('invalid')], { x: 100, y: 30 }, () => { throw new Error('out of range') })).toBeUndefined()
})

const handles: { dispose(): void }[] = []
afterEach(() => { handles.splice(0).forEach(handle => handle.dispose()); document.body.replaceChildren() })
function harness() {
  const root = document.createElement('div'), canvas = document.createElement('canvas')
  root.append(canvas); document.body.append(root)
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 10, top: 20, width: 800, height: 500 } as DOMRect)
  const sheet = { getSheetName: () => 'Sheet', getSheetId: () => 'sheet', getSheet: () => sheet }
  const book = { getId: () => 'book', getWorkbook: () => book, getActiveSheet: () => activeSheet }
  let activeSheet = sheet, activeBook: typeof book | null = book, available = true
  let changedSheet = () => {}
  const dirty = vi.fn(), change = vi.fn(), remove = vi.fn(), unsub = vi.fn()
  const scene = { getAncestorScale: () => ({ scaleX: 2, scaleY: 2 }), getActiveViewportByCoord: () => ({ viewportKey: SHEET_VIEWPORT_KEY.VIEW_MAIN }), getCoordRelativeToViewport: (point: {x:number;y:number}) => point, getScrollXYInfoByViewport: () => ({ x: 80, y: 20 }), makeDirty: dirty }
  const skeleton = { rowHeaderWidthAndMarginLeft: 46, columnHeaderHeightAndMarginTop: 20, getCellWithCoordByIndex: cellAt }
  const render = { scene, mainComponent: {makeDirty:dirty}, engine: { getCanvasElement: () => canvas }, with: (key: unknown) => key === SheetSkeletonManagerService ? { getCurrentSkeleton: () => skeleton } : undefined }
  const runtime = { univer: { __getInjector: () => ({ has: () => true, get: (key: unknown) => key === IRenderManagerService ? { getRenderById: () => render } : undefined }) }, univerAPI: { getActiveWorkbook: () => activeBook, Event: { ActiveSheetChanged:'active' }, addEvent: (_: string, callback: () => void) => { changedSheet = callback; return {dispose:unsub} } } } as unknown as UniverRuntime
  const charts = [chart('one'),chart('two',{fromRow:6,fromColumn:7,toRow:10,toColumn:11})]
  const elementChange=vi.fn()
  const handle = installWorkbookChartSelection(root,runtime,{ charts: () => charts, available: () => available, changed:change, remove,elementChanged:elementChange })
  handles.push(handle)
  // 原生变换：x/2 + scroll - header；此点实际为(300,160)。
  const pointer = (x=542,y=340,button=0,target:HTMLElement=canvas) => target.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true,cancelable:true,clientX:x,clientY:y,button}))
  return {root,canvas,handle,pointer,change,remove,dirty,unsub,charts,elementChange, setAvailable:(value:boolean)=>{available=value}, switchSheet:()=>{activeSheet={...sheet,getSheetId:()=> 'other',getSheet:()=> activeSheet};changedSheet()}, replaceBook:()=>{activeBook=null} }
}
it('真实画布元素点击先选系列，再缩至原点索引并向侧栏分发',()=>{const h=harness();setChartElementRegions('book','sheet',h.charts[1]!,[{element:{kind:'point',seriesIndex:0,pointIndex:2},contains:()=>true}]);h.pointer();expect(h.elementChange).toHaveBeenLastCalledWith({kind:'series',seriesIndex:0},{sheetName:'Sheet',chartPath:'two'});h.pointer();expect(h.handle.element()).toEqual({kind:'point',seriesIndex:0,pointIndex:2});expect(h.elementChange).toHaveBeenLastCalledWith({kind:'point',seriesIndex:0,pointIndex:2},{sheetName:'Sheet',chartPath:'two'})})
it('真实DOM指针经原生缩放滚动坐标选中第二张图，空白点击透传且清除选择', () => {
  const h=harness()
  expect(h.pointer()).toBe(false)
  expect(h.handle.current()).toEqual({sheetName:'Sheet',chartPath:'two'})
  expect(selectedChartPath('book','sheet')).toBe('two')
  expect(h.root.dataset.selectedChart).toBe('two')
  expect(h.pointer(20,50)).toBe(true)
  expect(h.handle.current()).toBeUndefined()
  expect(selectedChartPath('book','sheet')).toBeUndefined()
})
it('只选当前已解析图表，切表和替换工作簿不能复用旧身份', () => {
  const h=harness()
  expect(h.handle.select({sheetName:'Sheet',chartPath:'missing'})).toBe(false)
  expect(h.handle.select({sheetName:'Sheet',chartPath:'two'})).toBe(true)
  h.switchSheet();expect(h.handle.current()).toBeUndefined()
  h.handle.select({sheetName:'Sheet',chartPath:'one'});h.replaceBook()
  expect(h.handle.current()).toBeUndefined()
})
it('输入框/弹窗键盘与IME不被图表删除劫持，画布选中后Delete可分发', () => {
  const h=harness();h.pointer()
  const input=document.createElement('input');h.root.append(input)
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true,cancelable:true}))
  expect(h.remove).not.toHaveBeenCalled()
  h.root.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',isComposing:true,bubbles:true,cancelable:true}))
  expect(h.remove).not.toHaveBeenCalled()
  h.root.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true,cancelable:true}))
  expect(h.remove).toHaveBeenCalledOnce()
  h.root.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
  expect(h.handle.current()).toBeUndefined()
})
it('非主键、外来canvas和加载期间不接管，卸载清理选择和监听', () => {
  const h=harness(),foreign=document.createElement('canvas');h.root.append(foreign)
  expect(h.pointer(542,340,2)).toBe(true)
  expect(h.pointer(542,340,0,foreign)).toBe(true)
  h.setAvailable(false);expect(h.pointer()).toBe(true)
  h.setAvailable(true);h.pointer();h.handle.dispose()
  expect(h.root.dataset.selectedChart).toBeUndefined();expect(selectedChartPath('book','sheet')).toBeUndefined()
  expect(h.unsub).toHaveBeenCalledOnce();expect(h.pointer()).toBe(true)
})
it('修饰键删除与Escape快捷键不被图表选择处理器劫持', () => {
  const h = harness(); h.pointer()
  for (const modifier of ['altKey', 'ctrlKey', 'metaKey', 'shiftKey'] as const) {
    for (const key of ['Delete', 'Backspace', 'Escape']) {
      const event = new KeyboardEvent('keydown', { key, [modifier]: true, bubbles: true, cancelable: true })
      h.root.dispatchEvent(event)
      expect(event.defaultPrevented, `${modifier}+${key}`).toBe(false)
    }
  }
  expect(h.remove).not.toHaveBeenCalled()
  expect(h.handle.current()?.chartPath).toBe('two')
})
it('图表双击在捕获阶段阻止底层单元格进入编辑', () => {
  const h = harness(), editCell = vi.fn()
  h.canvas.addEventListener('dblclick', editCell)
  h.pointer()
  const event = new MouseEvent('dblclick', { clientX: 542, clientY: 340, button: 0, bubbles: true, cancelable: true })
  h.canvas.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
  expect(editCell).not.toHaveBeenCalled()
  expect(h.handle.current()?.chartPath).toBe('two')
})
it('接管从图表开始的pointerup，阻止引擎提前合成双击且普通单元格拖选透传', () => {
  const h = harness(), nativeUp = vi.fn()
  h.canvas.addEventListener('pointerup', nativeUp)
  const up = () => h.canvas.dispatchEvent(new MouseEvent('pointerup', { clientX: 542, clientY: 340, button: 0, bubbles: true, cancelable: true }))
  h.pointer(); expect(up()).toBe(false)
  h.pointer(); expect(up()).toBe(false)
  expect(nativeUp).not.toHaveBeenCalled()
  h.pointer(20, 50); expect(up()).toBe(true)
  expect(nativeUp).toHaveBeenCalledOnce()
  h.pointer(); h.canvas.dispatchEvent(new Event('pointercancel', { bubbles: true }))
  expect(up()).toBe(true)
  h.pointer(); h.handle.reset(); expect(up()).toBe(true)
})
it('图表手势在图框外或根节点外抬起也被收尾，外来触点和窗口失焦不沿用所有权', () => {
  const h = harness(), outside = document.createElement('div'); document.body.append(outside)
  const event = (type: string, pointerId = 1) => {
    const value = new MouseEvent(type, { clientX: 542, clientY: 340, button: type === 'pointercancel' ? -1 : 0, bubbles: true, cancelable: true })
    Object.defineProperty(value, 'pointerId', { value: pointerId }); return value
  }
  h.canvas.dispatchEvent(event('pointerdown'))
  expect(outside.dispatchEvent(event('pointerup', 2))).toBe(true)
  expect(outside.dispatchEvent(event('pointerup'))).toBe(false)
  h.canvas.dispatchEvent(event('pointerdown'))
  const upOutsideChart = new MouseEvent('pointerup', { clientX: 20, clientY: 50, bubbles: true, cancelable: true })
  Object.defineProperty(upOutsideChart, 'pointerId', { value: 1 })
  expect(h.canvas.dispatchEvent(upOutsideChart)).toBe(false)
  h.canvas.dispatchEvent(event('pointerdown')); window.dispatchEvent(new Event('blur'))
  expect(outside.dispatchEvent(event('pointerup'))).toBe(true)
})
