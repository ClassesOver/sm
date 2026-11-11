import type { Univer } from '@univerjs/core'
import { IRenderManagerService, SHEET_VIEWPORT_KEY } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import { CanvasFloatDomService } from '@univerjs/ui'
import { map } from 'rxjs'

/** 原生范围浮层会把跨冻结线的末端当作滚动单元格裁切；筛选控件应按锚点整体固定。 */
export function installPivotControlLayout(univer: Pick<Univer, '__getInjector'>, id: string, anchor: { row: number; column: number }): { dispose(): void } {
  const injector = univer.__getInjector(), service = injector.get(CanvasFloatDomService)
  const layer = service.domLayers.find(([key]) => key === id)?.[1]
  if (!layer) throw new Error('原生控件浮层布局不可用')
  const render = injector.get(IRenderManagerService).getRenderById(layer.unitId)
  if (!render) throw new Error('原生控件画布不可用')
  const source = layer.position$
  const position$ = source.pipe(map(position => {
    const skeleton = render.with(SheetSkeletonManagerService).getCurrentSkeleton()
    if (!skeleton) return position
    const freeze = skeleton.worksheet.getFreeze()
    const frozenRow = freeze.ySplit > 0 && anchor.row >= freeze.startRow - freeze.ySplit && anchor.row < freeze.startRow
    const frozenColumn = freeze.xSplit > 0 && anchor.column >= freeze.startColumn - freeze.xSplit && anchor.column < freeze.startColumn
    if (!frozenRow && !frozenColumn) return position
    const scene = render.scene
    const main = scene.getViewport(SHEET_VIEWPORT_KEY.VIEW_MAIN)
    const top = scene.getViewport(SHEET_VIEWPORT_KEY.VIEW_MAIN_TOP)
    const left = scene.getViewport(SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT)
    const corner = scene.getViewport(SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT_TOP)
    const panes = [main, top, left, corner].flatMap(pane => pane?.isActive && (pane.width ?? 0) > 0 && (pane.height ?? 0) > 0 ? [{ left: pane.left, top: pane.top, width: pane.width!, height: pane.height! }] : [])
    if (!panes.length) return position
    const canvas = render.engine.getCanvasElement(), { scaleX, scaleY } = scene.getAncestorScale()
    const minX = Math.max(0, Math.min(...panes.map(pane => pane.left)))
    const minY = Math.max(0, Math.min(...panes.map(pane => pane.top)))
    const maxX = Math.min(canvas.clientWidth, Math.max(...panes.map(pane => pane.left + pane.width)))
    const maxY = Math.min(canvas.clientHeight, Math.max(...panes.map(pane => pane.top + pane.height)))
    const cell = skeleton.getCellWithCoordByIndex(anchor.row, anchor.column)
    const frozenX = left?.isActive ? left : corner, frozenY = top?.isActive ? top : corner
    // 使用冻结视口的真实滚动偏移，兼容 RTL 将冻结列放在画布右侧的布局。
    const x = frozenColumn && frozenX ? (cell.startX - frozenX.viewportScrollX) * scaleX : position.startX
    const y = frozenRow && frozenY ? (cell.startY - frozenY.viewportScrollY) * scaleY : position.startY
    return {
      ...position,
      ...(frozenColumn ? { startX: Math.max(minX, x), endX: Math.max(minX, Math.min(maxX, x + position.width)) } : {}),
      ...(frozenRow ? { startY: Math.max(minY, y), endY: Math.max(minY, Math.min(maxY, y + position.height)) } : {}),
      absolute: { left: frozenColumn ? x >= minX : position.absolute.left, top: frozenRow ? y >= minY : position.absolute.top },
    }
  }))
  service.updateFloatDom(id, { position$ })
  return { dispose() { if (service.domLayers.find(([key]) => key === id)?.[1].position$ === position$) service.updateFloatDom(id, { position$: source }) } }
}
