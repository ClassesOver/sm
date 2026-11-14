import type { ChartReadSpec, DrawingAnchor } from '@sheets-web/xlsx-engine'
import type { UniverRuntime } from './workbook-vendor/grid/create-univer'
import type { SelectedWorkbookChart } from './workbook-chart-selection'
import { getTransformOffsetX, getTransformOffsetY } from '@univerjs/core'
import { IRenderManagerService, SHEET_VIEWPORT_KEY, Vector2 } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import { chartAtPoint, chartBounds } from './workbook-chart-geometry'
import { chartObjectAnchor, chartResizeHandleAt } from './workbook-chart-object-geometry'

export interface ChartObjectInteractionOptions<T> {
  charts(sheetName: string): readonly ChartReadSpec[]
  current(): SelectedWorkbookChart | undefined
  select(target: SelectedWorkbookChart): boolean
  selectElementAt?(target: SelectedWorkbookChart,x:number,y:number):void
  available(): boolean
  capture(chart: ChartReadSpec, sheetName: string): T
  validate(target: T): void
  commit(target: T, mode: 'move' | 'resize', anchor: DrawingAnchor): Promise<void>
  error(message: string): void
}
export function installWorkbookChartObjectInteraction<T>(root: HTMLElement, runtime: UniverRuntime, options: ChartObjectInteractionOptions<T>) {
  const owner = root.ownerDocument, win = owner.defaultView!
  const panes = new Set<string>([SHEET_VIEWPORT_KEY.VIEW_MAIN, SHEET_VIEWPORT_KEY.VIEW_MAIN_TOP, SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT, SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT_TOP])
  let disposed = false, pending = false, cancel: (() => void) | undefined, clickCanvas: HTMLCanvasElement | undefined
  let ownedPointer: number | undefined
  const pointerId = (event: Event) => 'pointerId' in event ? Number(event.pointerId) : 0
  const consume = (event: Event) => { event.preventDefault(); event.stopImmediatePropagation() }
  const click = (event: MouseEvent) => { if (event.target === clickCanvas) { clickCanvas = undefined; consume(event) } }
  const releaseOwned = (event: Event) => {
    if (ownedPointer === undefined || pointerId(event) !== ownedPointer) return
    ownedPointer = undefined
    // Esc/wheel可取消预览，但已认领的释放仍不能到达会合成单元格双击的引擎。
    event.preventDefault(); event.stopPropagation()
  }
  const blur = () => { ownedPointer = undefined; cancel?.() }
  const down = (event: PointerEvent) => {
    clickCanvas = undefined
    if (disposed || pending || cancel || !options.available() || event.button !== 0 || event.isPrimary === false || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getActiveSheet(), injector = runtime.univer.__getInjector?.()
    if (!book || !sheet || !injector?.has(IRenderManagerService)) return
    const render = injector.get(IRenderManagerService).getRenderById(book.getId()), canvas = render?.engine.getCanvasElement()
    if (!render || !canvas || event.target !== canvas || !root.contains(canvas)) return
    const skeleton = render.with(SheetSkeletonManagerService).getCurrentSkeleton()
    if (!skeleton) return
    const rect = canvas.getBoundingClientRect(), scene = render.scene, point = Vector2.FromArray([event.clientX - rect.left, event.clientY - rect.top])
    const pane = scene.getActiveViewportByCoord(point)
    if (!pane || !panes.has(pane.viewportKey)) return
    const relative = scene.getCoordRelativeToViewport(point), scroll = scene.getScrollXYInfoByViewport(relative, pane), scale = scene.getAncestorScale()
    if (!(scale.scaleX > 0 && scale.scaleY > 0)) return
    const x = getTransformOffsetX(relative.x, scale.scaleX, scroll, skeleton.rowHeaderWidthAndMarginLeft)
    const y = getTransformOffsetY(relative.y, scale.scaleY, scroll, skeleton.columnHeaderHeightAndMarginTop)
    const config = sheet.getSheet().getConfig(), rtl = config.rightToLeft === 1, charts = options.charts(sheet.getSheetName())
    // 固定源允许拖出数据大小的网格；预览用工作表真实默认宽高延伸，提交重放才扩网格。
    const cellAt = (row: number, column: number) => {
      const baseRow = Math.min(row, sheet.getMaxRows() - 1), baseColumn = Math.min(column, sheet.getMaxColumns() - 1)
      const cell = skeleton.getCellWithCoordByIndex(baseRow, baseColumn, false)
      const dx = (rtl ? -1 : 1) * (column - baseColumn) * Math.max(1, config.defaultColumnWidth)
      return { startX: cell.startX + dx, endX: cell.endX + dx, startY: cell.startY + (row - baseRow) * Math.max(1, config.defaultRowHeight) }
    }
    const selected = options.current(), active = selected?.sheetName === sheet.getSheetName() ? charts.find(chart => chart.chartPath === selected.chartPath) : undefined
    let corner = active?.anchorKind !== 'oneCellAnchor' && active?.anchorKind !== 'absoluteAnchor' && active
      ? chartResizeHandleAt(chartBounds(active.anchor, cellAt, rtl), x, y, scale.scaleX, scale.scaleY) : undefined
    const chart = corner ? active : chartAtPoint(charts, { x, y }, cellAt, rtl)
    if (!chart) return
    if (chart.anchorKind === 'absoluteAnchor') { options.error('源 writer 不支持绝对锚点图表移动或缩放'); return }
    let target: T
    try {
      if (!options.select({ sheetName: sheet.getSheetName(), chartPath: chart.chartPath })) return
      target = options.capture(chart, sheet.getSheetName()); options.validate(target)
      if(!corner)options.selectElementAt?.({sheetName:sheet.getSheetName(),chartPath:chart.chartPath},x,y)
    } catch (reason) { options.error((reason as Error).message); return }
    const before: DrawingAnchor = { fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0, ...chart.anchor }
    const mode = corner ? 'resize' : 'move'; corner ??= 'se'
    const bounds = chartBounds(chart.anchor, cellAt, rtl), origin = { x: event.clientX + (bounds.x0 - x) * scale.scaleX, y: event.clientY + (bounds.y0 - y) * scale.scaleY }
    const grid = {
      columnWidth: (index: number) => index < sheet.getMaxColumns() ? sheet.getColumnWidth(index) : config.defaultColumnWidth,
      rowHeight: (index: number) => index < sheet.getMaxRows() ? sheet.getRowHeight(index) : config.defaultRowHeight,
      scaleX: scale.scaleX, scaleY: scale.scaleY, rtl,
    }
    let stopped = false, preview: HTMLElement | undefined
    const previousCursor = canvas.style.cursor
    canvas.style.cursor = mode === 'move' ? 'move' : `${corner}-resize`
    const cleanup = () => {
      if (stopped) return
      stopped = true; cancel = undefined; preview?.remove(); canvas.style.cursor = previousCursor
      win.removeEventListener('pointermove', move, true); win.removeEventListener('pointerup', up, true)
      win.removeEventListener('pointercancel', pointerCancel, true); win.removeEventListener('keydown', key, true)
      win.removeEventListener('wheel', cleanup, true); win.removeEventListener('blur', cleanup); win.removeEventListener('resize', cleanup)
      canvas.removeEventListener('lostpointercapture', cleanup)
      if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    }
    const validate = () => {
      options.validate(target)
      const nextScale = scene.getAncestorScale(), nextScroll = scene.getScrollXYInfoByViewport(relative, pane)
      if (nextScale.scaleX !== scale.scaleX || nextScale.scaleY !== scale.scaleY || nextScroll.x !== scroll.x || nextScroll.y !== scroll.y || (sheet.getSheet().getConfig().rightToLeft === 1) !== rtl)
        throw new Error('图表视图已变化，请重新拖动')
    }
    const value = (next: PointerEvent) => chartObjectAnchor(before, mode, corner!, next.clientX - event.clientX, next.clientY - event.clientY, grid)
    const move = (next: PointerEvent) => {
      if (pointerId(next) !== pointerId(event)) return
      consume(next)
      try {
        validate()
        if (Math.hypot(next.clientX - event.clientX, next.clientY - event.clientY) < 3) return
        const anchor = value(next), nextBounds = chartBounds(anchor, cellAt, rtl)
        if (!preview) { preview = owner.createElement('div'); preview.dataset.chartGeometryPreview = chart.chartPath; preview.setAttribute('aria-hidden', 'true'); owner.body.append(preview) }
        Object.assign(preview.style, { position: 'fixed', pointerEvents: 'none', zIndex: '1000', border: '2px solid #2563eb', boxSizing: 'border-box',
          left: `${origin.x + (nextBounds.x0 - bounds.x0) * scale.scaleX}px`, top: `${origin.y + (nextBounds.y0 - bounds.y0) * scale.scaleY}px`,
          width: `${(nextBounds.x1 - nextBounds.x0) * scale.scaleX}px`, height: `${(nextBounds.y1 - nextBounds.y0) * scale.scaleY}px` })
      } catch (reason) { cleanup(); options.error((reason as Error).message) }
    }
    const up = (next: PointerEvent) => {
      if (pointerId(next) !== pointerId(event)) return
      consume(next)
      try {
        validate()
        if (Math.hypot(next.clientX - event.clientX, next.clientY - event.clientY) < 3) return
        const anchor = value(next)
        if (Object.entries(before).every(([key, old]) => anchor[key as keyof DrawingAnchor] === old)) return
        clickCanvas = canvas
        pending = true
        void options.commit(target, mode, anchor).catch(reason => options.error((reason as Error).message)).finally(() => { pending = false })
      } catch (reason) { options.error((reason as Error).message) }
      finally { cleanup() }
    }
    const pointerCancel = (next: PointerEvent) => { if (pointerId(next) === pointerId(event)) { consume(next); cleanup() } }
    const key = (next: KeyboardEvent) => { if (!next.isComposing && !next.defaultPrevented && next.key === 'Escape') { consume(next); cleanup() } }
    cancel = cleanup
    ownedPointer = pointerId(event)
    canvas.setPointerCapture?.(event.pointerId)
    canvas.addEventListener('lostpointercapture', cleanup)
    win.addEventListener('pointermove', move, true); win.addEventListener('pointerup', up, true); win.addEventListener('pointercancel', pointerCancel, true)
    win.addEventListener('keydown', key, true); win.addEventListener('wheel', cleanup, { capture: true, passive: true }); win.addEventListener('blur', cleanup); win.addEventListener('resize', cleanup)
    root.focus({ preventScroll: true }); consume(event)
  }
  // 在原选择处理器前认领完整手势，八个控制点在图框外也不会被网格选择抢走。
  win.addEventListener('pointerdown', down, true); win.addEventListener('click', click, true)
  win.addEventListener('pointerup', releaseOwned, true); win.addEventListener('pointercancel', releaseOwned, true); win.addEventListener('blur', blur)
  const subscription = runtime.univerAPI.Event?.ActiveSheetChanged ? runtime.univerAPI.addEvent(runtime.univerAPI.Event.ActiveSheetChanged, () => cancel?.()) : undefined
  return { cancel() { cancel?.() }, dispose() { if (disposed) return; disposed = true; ownedPointer = undefined; cancel?.(); subscription?.dispose(); win.removeEventListener('pointerdown', down, true); win.removeEventListener('click', click, true); win.removeEventListener('pointerup', releaseOwned, true); win.removeEventListener('pointercancel', releaseOwned, true); win.removeEventListener('blur', blur) } }
}
