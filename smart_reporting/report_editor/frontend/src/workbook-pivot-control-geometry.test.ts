import { afterEach, expect, it, vi } from 'vitest'
import { BehaviorSubject } from 'rxjs'
import { BooleanNumber, IUniverInstanceService, LocaleType, Univer, UniverInstanceType, type Workbook } from '@univerjs/core'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { IRenderManagerService, SHEET_VIEWPORT_KEY, SpreadsheetSkeleton } from '@univerjs/engine-render'
import { CanvasFloatDomService, type IFloatDomLayout } from '@univerjs/ui'
import { installPivotControlGeometry } from './workbook-pivot-control-geometry'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { installRtlGridMirror } from './vendor/genoffice-rtl/rtl-grid-mirror'

const disposables: (() => void)[] = []
afterEach(() => disposables.splice(0).reverse().forEach(dispose => dispose()))
function fixture(scale = 1) {
  const service = new CanvasFloatDomService(), commit = vi.fn(async (_anchor: { row: number; column: number; width?: number; height?: number }) => {}), error = vi.fn()
  const source = new BehaviorSubject<IFloatDomLayout>({ startX: 100, startY: 100, endX: 100 + 192 * scale, endY: 100 + 260 * scale, width: 192 * scale, height: 260 * scale, rotate: 0, absolute: { left: true, top: true } })
  service.addFloatDom({ id: 'control', unitId: 'book', componentKey: 'control', position$: source, onPointerDown() {}, onPointerMove() {}, onPointerUp() {}, onWheel() {} })
  const form = document.createElement('form'), button = document.createElement('button'); button.type = 'button'; form.append(button); document.body.append(form)
  form.getBoundingClientRect = () => ({ x: 110, y: 120, left: 110, top: 120, right: 110 + 192 * scale - 4, bottom: 120 + 260 * scale - 4, width: 192 * scale - 4, height: 260 * scale - 4, toJSON() {} })
  button.setPointerCapture = vi.fn(); button.releasePointerCapture = vi.fn(); button.hasPointerCapture = () => true
  const pane = { viewportKey: SHEET_VIEWPORT_KEY.VIEW_MAIN, isActive: true, left: 40, top: 20, width: 660, height: 480, viewportScrollX: 0, viewportScrollY: 0 }
  const hit = vi.fn((x: number, y: number, sx = scale, sy = scale, scroll = { x: 0, y: 0 }) => ({ actualRow: Math.floor((y / sy + scroll.y - 20) / 20), actualColumn: Math.floor((x / sx + scroll.x - 40) / 50) }))
  const scene = { getViewports: () => [pane], getAncestorScale: () => ({ scaleX: scale, scaleY: scale }), getActiveViewportByCoord: (point: { x: number; y: number }) => point.x >= 40 && point.x < 700 && point.y >= 20 && point.y < 500 ? pane : undefined, getCoordRelativeToViewport: (point: unknown) => point, getScrollXYInfoByViewport: () => ({ x: pane.viewportScrollX, y: pane.viewportScrollY }) }
  const render = { scene, with: () => ({ getCurrentSkeleton: () => ({ getCellWithCoordByOffset: hit }) }), engine: { getCanvasElement: () => ({ getBoundingClientRect: () => ({ left: 10, top: 20 }) }) } }
  const univer = { __getInjector: () => ({ get: (token: unknown) => token === CanvasFloatDomService ? service : token === IRenderManagerService ? { getRenderById: () => render } : undefined }) } as unknown as Pick<Univer, '__getInjector'>
  let editable = true
  const handle = installPivotControlGeometry(univer, 'control', { row: 4, column: 1, width: 192, height: 260 }, { canEdit: () => editable, commit, error })
  const event = (type: string, x: number, y: number, id = 1) => {
    const event = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true, cancelable: true })
    Object.defineProperty(event, 'pointerId', { value: id }); return event as PointerEvent
  }
  disposables.push(() => { handle.dispose(); source.complete(); form.remove() })
  return { service, source, button, commit, error, hit, handle, pane, event, lock() { editable = false }, dispatch(type: string, x: number, y: number, id = 1) { window.dispatchEvent(event(type, x, y, id)) } }
}

it('previews a move and commits one snapped anchor only after release', async () => {
  const f = fixture()
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'move')
  f.dispatch('pointermove', 220, 170)
  let layout!: IFloatDomLayout
  const subscription = f.service.domLayers[0]![1].position$.subscribe(value => { layout = value })
  expect(layout).toMatchObject({ startX: 200, startY: 140, width: 192, height: 260 })
  expect(f.commit).not.toHaveBeenCalled()
  f.dispatch('pointerup', 220, 170); await Promise.resolve()
  expect(f.commit).toHaveBeenCalledExactlyOnceWith({ row: 6, column: 3, width: 192, height: 260 })
  expect(f.service.domLayers[0]![1].position$).toBe(f.source)
  expect(f.button.releasePointerCapture).toHaveBeenCalledWith(1)
  subscription.unsubscribe()
})

it.each(['composition', 'legacy', 'handled'])('受保护Escape不撤回透视控件拖动，松开仍只提交一次：%s', async protection => {
  const f = fixture()
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'move'); f.dispatch('pointermove', 220, 170)
  const preview = f.service.domLayers[0]![1].position$
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
  if (protection === 'handled') event.preventDefault()
  window.dispatchEvent(event)
  expect(f.service.domLayers[0]![1].position$).toBe(preview)
  expect(f.button.releasePointerCapture).not.toHaveBeenCalled()
  expect(f.commit).not.toHaveBeenCalled()
  f.dispatch('pointerup', 220, 170); await Promise.resolve()
  expect(f.commit).toHaveBeenCalledExactlyOnceWith({ row: 6, column: 3, width: 192, height: 260 })
  expect(f.service.domLayers[0]![1].position$).toBe(f.source)
})

it('resizes in unscaled integer pixels and clamps native schema limits', async () => {
  const f = fixture(1.25)
  f.handle.start(f.event('pointerdown', 200, 200), f.button, 'resize')
  f.dispatch('pointerup', 300, 250); await Promise.resolve()
  expect(f.commit).toHaveBeenCalledExactlyOnceWith({ row: 4, column: 1, width: 272, height: 300 })
  await Promise.resolve(); await Promise.resolve()
  f.handle.start(f.event('pointerdown', 200, 200), f.button, 'resize')
  f.dispatch('pointerup', -800, -800); await Promise.resolve(); await Promise.resolve()
  expect(f.commit.mock.calls.at(-1)?.[0]).toEqual({ row: 4, column: 1, width: 96, height: 80 })
})

it('restores the original layout and reports a failed geometry transaction', async () => {
  const f = fixture(); f.commit.mockRejectedValueOnce(new Error('stale control'))
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'resize'); f.dispatch('pointerup', 220, 170)
  await Promise.resolve(); await Promise.resolve()
  expect(f.error).toHaveBeenCalledWith('stale control')
  expect(f.service.domLayers[0]![1].position$).toBe(f.source)
})

it.each(['escape', 'pointercancel', 'dispose', 'scroll', 'lock', 'outside'])('cancels %s without committing or retaining a preview layer', async reason => {
  const f = fixture()
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'move'); f.dispatch('pointermove', 220, 170)
  if (reason === 'escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  if (reason === 'pointercancel') f.dispatch('pointercancel', 220, 170)
  if (reason === 'dispose') f.handle.dispose()
  if (reason === 'scroll') f.source.next({ ...f.source.value, startY: 90 })
  if (reason === 'lock') f.lock()
  f.dispatch('pointerup', reason === 'outside' ? 2000 : 220, 170); await Promise.resolve()
  expect(f.commit).not.toHaveBeenCalled()
  expect(f.service.domLayers[0]![1].position$).toBe(f.source)
})

it('ignores other pointers, unchanged clicks, and protected starts', async () => {
  const f = fixture()
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'move'); f.dispatch('pointerup', 220, 170, 2)
  expect(f.commit).not.toHaveBeenCalled()
  f.dispatch('pointerup', 120, 130)
  f.lock(); f.handle.start(f.event('pointerdown', 120, 130), f.button, 'resize'); f.dispatch('pointerup', 220, 170)
  await Promise.resolve(); expect(f.commit).not.toHaveBeenCalled()
})

it('uses the native viewport hit mapping for mirrored or frozen coordinates', async () => {
  const f = fixture()
  f.hit.mockReturnValue({ actualRow: 5, actualColumn: 12 })
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'move'); f.dispatch('pointerup', 220, 170)
  await Promise.resolve(); expect(f.commit).toHaveBeenCalledExactlyOnceWith({ row: 5, column: 12, width: 192, height: 260 })
})

it.each([1, 1.25])('uses real RTL skeleton hit mapping with nonzero viewport scroll at scale %s', async scale => {
  installRtlGridMirror()
  const data = buildWorkbookData(await readWorkbook(await createBlankWorkbook()), 'geometry-rtl', 'geometry')
  Object.assign(data.sheets[data.sheetOrder[0]!]!, { rightToLeft: BooleanNumber.TRUE })
  const univer = new Univer({ locale: LocaleType.EN_US }); univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, data)
  const workbook = univer.__getInjector().get(IUniverInstanceService).getUnit<Workbook>('geometry-rtl')!
  const skeleton = univer.__getInjector().createInstance(SpreadsheetSkeleton, workbook.getActiveSheet()!, workbook.getStyles())
  disposables.push(() => { skeleton.dispose(); univer.dispose() })
  const f = fixture(scale), from = skeleton.getCellWithCoordByIndex(4, 1), to = skeleton.getCellWithCoordByIndex(6, 0)
  f.pane.viewportScrollX = from.startX - 100 / scale; f.pane.viewportScrollY = from.startY - 100 / scale
  f.hit.mockImplementation((x, y, sx, sy, scroll) => skeleton.getCellWithCoordByOffset(x, y, sx, sy, scroll))
  f.handle.start(f.event('pointerdown', 120, 130), f.button, 'move')
  f.dispatch('pointerup', 120 + (to.startX - f.pane.viewportScrollX) * scale - 100 + 2, 130 + (to.startY - f.pane.viewportScrollY) * scale - 100 + 2)
  await Promise.resolve()
  expect(f.commit).toHaveBeenCalledExactlyOnceWith({ row: 6, column: 0, width: 192, height: 260 })
})
