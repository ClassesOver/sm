import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { getTransformOffsetX, getTransformOffsetY } from '@univerjs/core'
import { IRenderManagerService, SHEET_VIEWPORT_KEY, Vector2 } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import { chartAtPoint } from './workbook-chart-geometry'
import {hitChartElement,narrowChartElement,type WorkbookChartElement} from './workbook-chart-element-hit'
import { setSelectedChartPath } from './workbook-chart-selection-state'
export { selectedChartPath } from './workbook-chart-selection-state'
import type { UniverRuntime } from './workbook-vendor/grid/create-univer'

export interface SelectedWorkbookChart { sheetName: string; chartPath: string }
export interface ChartSelectionOptions {
  charts(sheetName: string): readonly ChartReadSpec[]
  available(): boolean
  changed(target: SelectedWorkbookChart | undefined): void
  remove(): void
  elementChanged?(element:WorkbookChartElement,target:SelectedWorkbookChart):void
}

const gridPanes = new Set<string>([SHEET_VIEWPORT_KEY.VIEW_MAIN, SHEET_VIEWPORT_KEY.VIEW_MAIN_TOP, SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT, SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT_TOP])

export function installWorkbookChartSelection(root: HTMLElement, runtime: UniverRuntime, options: ChartSelectionOptions) {
  let disposed = false
  let chartPointerId: number | undefined
  let element:WorkbookChartElement|undefined
  let selected: { target: SelectedWorkbookChart; book: object; sheet: object; unitId: string; sheetId: string } | undefined
  const previousTabIndex = root.getAttribute('tabindex')
  if (previousTabIndex === null) root.tabIndex = 0
  const renderOf = (unitId: string) => {
    const injector = runtime.univer.__getInjector?.()
    return injector?.has(IRenderManagerService) ? injector.get(IRenderManagerService).getRenderById(unitId) : undefined
  }
  const dirty = (unitId: string) => { try { const render = renderOf(unitId); render?.mainComponent?.makeDirty(true);render?.scene.makeDirty(true) } catch { /* 渲染器可能已随工作簿释放。 */ } }
  const clear = () => {
    chartPointerId = undefined
    if (!selected) return
    element=undefined
    setSelectedChartPath(selected.unitId,selected.sheetId);dirty(selected.unitId);selected = undefined
    delete root.dataset.selectedChart;options.changed(undefined)
  }
  const current = () => {
    const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getActiveSheet()
    if (selected && (disposed || book?.getWorkbook() !== selected.book || sheet?.getSheet() !== selected.sheet ||
      !options.charts(selected.target.sheetName).some(chart => chart.chartPath === selected!.target.chartPath))) clear()
    return selected?.target
  }
  const select = (target: SelectedWorkbookChart) => {
    if (disposed || !options.available()) return false
    const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getActiveSheet()
    if (!book || !sheet || sheet.getSheetName() !== target.sheetName || !options.charts(target.sheetName).some(chart => chart.chartPath === target.chartPath)) return false
    if(selected?.book===book.getWorkbook()&&selected.sheet===sheet.getSheet()&&selected.target.chartPath===target.chartPath)return true
    clear()
    selected = { target: { ...target }, book: book.getWorkbook(), sheet: sheet.getSheet(), unitId: book.getId(), sheetId: sheet.getSheetId() }
    setSelectedChartPath(selected.unitId,selected.sheetId,target.chartPath)
    root.dataset.selectedChart = target.chartPath;dirty(selected.unitId);options.changed(selected.target)
    return true
  }
  const selectElementAt = (target: SelectedWorkbookChart,x:number,y:number) => {
    if(!select(target)||!selected)return
    const chart=options.charts(target.sheetName).find(chart=>chart.chartPath===target.chartPath)
    if(!chart)return
    element=narrowChartElement(element,hitChartElement(selected.unitId,selected.sheetId,chart,x,y))
    options.elementChanged?.(element,selected.target)
  }
  const pointer = (event: MouseEvent) => {
    if ('isPrimary' in event && event.isPrimary === false) return
    if (event.type === 'pointerdown') chartPointerId = undefined
    if (disposed || !options.available() || event.button !== 0) return
    const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getActiveSheet()
    if (!book || !sheet) return
    const render = renderOf(book.getId()), canvas = render?.engine.getCanvasElement()
    if (!render || event.target !== canvas) return
    const skeleton = render.with(SheetSkeletonManagerService).getCurrentSkeleton()
    if (!skeleton) return
    const rect = canvas.getBoundingClientRect(), scene = render.scene
    const point = Vector2.FromArray([event.clientX - rect.left, event.clientY - rect.top])
    const pane = scene.getActiveViewportByCoord(point)
    if (!pane || !gridPanes.has(pane.viewportKey)) { clear();return }
    const relative = scene.getCoordRelativeToViewport(point), scroll = scene.getScrollXYInfoByViewport(relative, pane), scale = scene.getAncestorScale()
    const x = getTransformOffsetX(relative.x, scale.scaleX, scroll, skeleton.rowHeaderWidthAndMarginLeft)
    const y = getTransformOffsetY(relative.y, scale.scaleY, scroll, skeleton.columnHeaderHeightAndMarginTop)
    const chart = chartAtPoint(options.charts(sheet.getSheetName()), { x, y }, (row, column) => skeleton.getCellWithCoordByIndex(row, column, false), sheet.getSheet().getConfig?.().rightToLeft === 1)
    if (!chart) { clear();return }
    if (!select({ sheetName: sheet.getSheetName(), chartPath: chart.chartPath })) return
    if(event.type==='pointerdown')selectElementAt({sheetName:sheet.getSheetName(),chartPath:chart.chartPath},x,y)
    if (event.type === 'pointerdown') chartPointerId = pointerId(event)
    root.focus({ preventScroll: true });event.preventDefault();event.stopPropagation()
  }
  const key = (event: KeyboardEvent) => {
    if (disposed || event.target !== root || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || !options.available() || !current()) return
    if (event.key === 'Escape') clear()
    else if (event.key === 'Delete' || event.key === 'Backspace') options.remove()
    else return
    event.preventDefault();event.stopPropagation()
  }
  const pointerId = (event: Event) => 'pointerId' in event && typeof event.pointerId === 'number' ? event.pointerId : 0
  const endPointer = (event: Event) => {
    if (chartPointerId === undefined || pointerId(event) !== chartPointerId) return
    chartPointerId = undefined
    // 引擎会在 pointerup 合成双击；仅消费已认领手势，含移出图框后的释放。
    event.preventDefault(); event.stopPropagation()
  }
  const cancelPointer = () => { chartPointerId = undefined }
  const ownerWindow = root.ownerDocument.defaultView
  root.addEventListener('pointerdown',pointer,true);root.addEventListener('click',pointer,true);root.addEventListener('dblclick',pointer,true);root.addEventListener('keydown',key,true)
  ownerWindow?.addEventListener('pointerup',endPointer,true);ownerWindow?.addEventListener('pointercancel',endPointer,true);ownerWindow?.addEventListener('blur',cancelPointer)
  const subscription = runtime.univerAPI.Event?.ActiveSheetChanged ? runtime.univerAPI.addEvent(runtime.univerAPI.Event.ActiveSheetChanged,clear) : undefined
  return { current, select, selectElementAt, element:()=>element,
    reset(target?: SelectedWorkbookChart) { clear();if (target) select(target) },
    dispose() { if (disposed) return;clear();disposed = true;subscription?.dispose();root.removeEventListener('pointerdown',pointer,true);root.removeEventListener('click',pointer,true);root.removeEventListener('dblclick',pointer,true);root.removeEventListener('keydown',key,true);ownerWindow?.removeEventListener('pointerup',endPointer,true);ownerWindow?.removeEventListener('pointercancel',endPointer,true);ownerWindow?.removeEventListener('blur',cancelPointer);if (previousTabIndex === null) root.removeAttribute('tabindex') },
  }
}
