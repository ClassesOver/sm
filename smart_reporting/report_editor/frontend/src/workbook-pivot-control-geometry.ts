import type { Univer } from '@univerjs/core'
import { IRenderManagerService, SHEET_VIEWPORT_KEY, Vector2 } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import { CanvasFloatDomService, type IFloatDomLayout } from '@univerjs/ui'
import { BehaviorSubject, skip, take } from 'rxjs'
import type { PivotControl } from '@sheets-web/xlsx-engine/pivot-controls'

export type PivotControlAnchor = NonNullable<PivotControl['anchor']>
interface GeometryActions {
  canEdit(): boolean
  commit(anchor: PivotControlAnchor): Promise<void>
  error(message: string): void
}
const paneKeys = new Set<string>([SHEET_VIEWPORT_KEY.VIEW_MAIN, SHEET_VIEWPORT_KEY.VIEW_MAIN_TOP, SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT, SHEET_VIEWPORT_KEY.VIEW_MAIN_LEFT_TOP])

/** 预览仅替换 owned 浮层布局流；松开后才提交既有 OOXML anchor，不注册另一份绘图。 */
export function installPivotControlGeometry(univer: Pick<Univer, '__getInjector'>, id: string, anchor: PivotControlAnchor, actions: GeometryActions) {
  const injector = univer.__getInjector(), service = injector.get(CanvasFloatDomService)
  let disposed = false, pending = false, cancel: (() => void) | undefined
  return {
    start(event: PointerEvent, target: HTMLElement, mode: 'move' | 'resize') {
      if (disposed || pending || cancel || event.button !== 0 || !actions.canEdit()) return
      const form = target.closest('form')
      if (form?.querySelector('fieldset')?.disabled) return
      const layer = service.domLayers.find(([key]) => key === id)?.[1]
      const render = layer && injector.get(IRenderManagerService).getRenderById(layer.unitId)
      const skeleton = render?.with(SheetSkeletonManagerService).getCurrentSkeleton()
      if (!form || !layer || !render || !skeleton) return
      const source = layer.position$
      let base: IFloatDomLayout | undefined
      source.pipe(take(1)).subscribe(value => { base = value })
      if (!base) return
      const original = base, scene = render.scene, canvas = render.engine.getCanvasElement().getBoundingClientRect()
      const rect = form.getBoundingClientRect(), { scaleX, scaleY } = scene.getAncestorScale()
      const panes = scene.getViewports().filter(pane => pane.isActive && paneKeys.has(pane.viewportKey) && (pane.width ?? 0) > 0 && (pane.height ?? 0) > 0)
      if (!panes.length) return
      const minX = Math.min(...panes.map(pane => pane.left)), minY = Math.min(...panes.map(pane => pane.top))
      const maxX = Math.max(...panes.map(pane => pane.left + pane.width!)), maxY = Math.max(...panes.map(pane => pane.top + pane.height!))
      const origin = { x: rect.left - canvas.left, y: rect.top - canvas.top }
      const preview = new BehaviorSubject(original), position$ = preview.asObservable()
      let stopped = false
      const dimensions = (dx: number, dy: number) => ({
        width: Math.max(96, Math.min(2000, Math.round((original.width + dx) / scaleX))),
        height: Math.max(80, Math.min(2000, Math.round((original.height + dy) / scaleY))),
      })
      const move = (next: PointerEvent) => {
        if (next.pointerId !== event.pointerId) return
        if (!actions.canEdit()) { cleanup(); return }
        const dx = next.clientX - event.clientX, dy = next.clientY - event.clientY
        const x = origin.x + (mode === 'move' ? dx : 0), y = origin.y + (mode === 'move' ? dy : 0)
        const size = dimensions(dx, dy), width = mode === 'resize' ? size.width * scaleX : original.width, height = mode === 'resize' ? size.height * scaleY : original.height
        preview.next({ ...original, startX: Math.max(minX, x), startY: Math.max(minY, y), endX: Math.max(minX, Math.min(maxX, x + width)), endY: Math.max(minY, Math.min(maxY, y + height)), width, height, absolute: { left: x >= minX, top: y >= minY } })
        next.preventDefault(); next.stopPropagation()
      }
      const up = (next: PointerEvent) => {
        if (next.pointerId !== event.pointerId) return
        const allowed = actions.canEdit(), dx = next.clientX - event.clientX, dy = next.clientY - event.clientY
        cleanup()
        if (!allowed || Math.hypot(dx, dy) < 3) return
        let value: PivotControlAnchor
        if (mode === 'resize') value = { ...anchor, ...dimensions(dx, dy) }
        else {
          const point = Vector2.FromArray([origin.x + dx, origin.y + dy])
          const pane = scene.getActiveViewportByCoord(point)
          if (!pane || !paneKeys.has(pane.viewportKey)) { actions.error('请将控件移动到工作表可见网格内'); return }
          // skeleton 的 offset API 自行应用 scroll，不能在输入坐标中再次扣除。
          const relative = scene.getCoordRelativeToViewport(point), scroll = scene.getScrollXYInfoByViewport(relative, pane)
          const cell = skeleton.getCellWithCoordByOffset(relative.x, relative.y, scaleX, scaleY, scroll)
          if (!cell || cell.actualRow < 0 || cell.actualRow > 1048575 || cell.actualColumn < 0 || cell.actualColumn > 16383) { actions.error('控件位置超出工作表范围'); return }
          value = { ...anchor, row: cell.actualRow, column: cell.actualColumn }
        }
        if (value.row === anchor.row && value.column === anchor.column && value.width === anchor.width && value.height === anchor.height) return
        pending = true
        void actions.commit(value).catch(reason => actions.error((reason as Error).message)).finally(() => { pending = false })
        next.preventDefault(); next.stopPropagation()
      }
      const pointerCancel = (next: PointerEvent) => { if (next.pointerId === event.pointerId) cleanup() }
      const key = (next: KeyboardEvent) => { if (next.key === 'Escape') { cleanup(); next.preventDefault(); next.stopPropagation() } }
      const cleanup = () => {
        if (stopped) return
        stopped = true; cancel = undefined
        window.removeEventListener('pointermove', move, true); window.removeEventListener('pointerup', up, true)
        window.removeEventListener('pointercancel', pointerCancel, true); window.removeEventListener('keydown', key, true)
        window.removeEventListener('wheel', cleanup, true); window.removeEventListener('resize', cleanup)
        target.removeEventListener('lostpointercapture', cleanup)
        changed.unsubscribe()
        if (service.domLayers.find(([name]) => name === id)?.[1].position$ === position$) service.updateFloatDom(id, { position$: source })
        preview.complete()
        if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId)
      }
      const changed = source.pipe(skip(1)).subscribe(() => cleanup())
      cancel = cleanup
      target.setPointerCapture(event.pointerId)
      target.addEventListener('lostpointercapture', cleanup)
      window.addEventListener('pointermove', move, true); window.addEventListener('pointerup', up, true)
      window.addEventListener('pointercancel', pointerCancel, true); window.addEventListener('keydown', key, true)
      window.addEventListener('wheel', cleanup, { capture: true, passive: true }); window.addEventListener('resize', cleanup)
      service.updateFloatDom(id, { position$ })
      event.preventDefault(); event.stopPropagation()
    },
    dispose() { disposed = true; cancel?.() },
  }
}
