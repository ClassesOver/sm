import { act, createElement, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { afterAll, expect, it, vi } from 'vitest'
import { BehaviorSubject } from 'rxjs'
import { CanvasFloatDomService, type IFloatDomLayout } from '@univerjs/ui'
import { IRenderManagerService } from '@univerjs/engine-render'
import { createBlankWorkbook, applyCellEdits } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan } from './workbook-pivot'
import { readPivotControlViews, installPivotControlOverlay, type PivotControlView } from './workbook-pivot-controls'

vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
afterAll(() => vi.unstubAllGlobals())

const view: PivotControlView = {
  control: { kind: 'slicer', tablePath: 'xl/pivotTables/pivotTable1.xml', field: '地区', name: 'RegionSlicer', caption: '销售地区', partPath: 'xl/slicers/slicer1.xml', cachePath: 'xl/slicerCaches/slicerCache1.xml', anchor: { row: 4, column: 12, width: 320, height: 180 } },
  pivot: { name: '销售', tablePath: 'xl/pivotTables/pivotTable1.xml', cachePath: 'cache', worksheetPath: 'sheet', fieldNames: ['地区', '金额'], location: { startRow: 0, endRow: 3, startColumn: 4, endColumn: 5 }, sourceSheetName: '数据', sourceRange: 'A1:B3', targetSheetName: '汇总', targetCell: 'E1', rowFields: ['地区'], columnFields: [], values: [{ field: '金额', agg: 'sum' }], hiddenMembers: { row: [['西']], column: [] } },
  fields: [{ name: '地区', axis: 'row', level: 0, timeline: false, members: [{ value: '东' }, { value: '西' }] }],
}

function harness() {
  const host = document.createElement('div'); document.body.append(host)
  const components = new Map<string, ComponentType>(), ranges: number[][] = []
  let name = '汇总', sheetChanged = () => {}, commandExecuted = (_command: { id: string }) => {}
  const floats = vi.fn((_range: number[], layer: { componentKey: string; allowTransform: boolean; eventPassThrough: boolean }, _layout: { width: number; height: number }) => {
    const element = document.createElement('div'); host.append(element)
    const root = createRoot(element)
    root.render(createElement(components.get(layer.componentKey)!))
    return { dispose() { root.unmount(); element.remove() } }
  })
  const sheet = { getSheetName: () => name, getRange: (...args: number[]) => { ranges.push(args); return args }, addFloatDomToRange: floats }
  const eventDispose = vi.fn()
  const commandDispose = vi.fn()
  const runtime = { univerAPI: { registerComponent(key: string, component: ComponentType) { components.set(key, component); return { dispose() { components.delete(key) } } }, getActiveWorkbook: () => ({ getActiveSheet: () => sheet }), Event: { ActiveSheetChanged: 'sheet' }, addEvent(_event: string, callback: () => void) { sheetChanged = callback; return { dispose: eventDispose } }, onCommandExecuted(callback: (command: { id: string }) => void) { commandExecuted = callback; return { dispose: commandDispose } } } }
  return { host, runtime, floats, ranges, components, eventDispose, commandDispose, command(id: string) { commandExecuted({ id }) }, switchSheet(next: string) { name = next; sheetChanged() }, cleanup() { host.remove() } }
}

it('projects validated owned controls with current pivot member selections', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [['地区', '金额'], ['东', 10], ['西', 20]].flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  const config = { ...view.pivot, sourceSheetName: 'Sheet1', targetSheetName: 'Sheet1', hiddenMembers: undefined }
  const plan = await createPivotPlan(source, config)
  const bytes = await applyWorkbookOperations(source, [...plan.operations, { kind: 'upsertPivotControl', request: { kind: 'slicer', tablePath: view.control.tablePath, field: '地区', name: 'RegionSlicer', anchor: view.control.anchor } }])
  const result = await readPivotControlViews(bytes)
  expect(result).toHaveLength(1)
  expect(result[0]!.pivot.targetSheetName).toBe('Sheet1')
  expect(result[0]!.control.anchor).toEqual(view.control.anchor)
  expect(result[0]!.fields[0]!.members.map(member => member.value)).toEqual(['东', '西'])
  expect(await readPivotControlViews(source)).toEqual([])
})

it('anchors an interactive slicer and applies member choices through the existing planner', async () => {
  const h = harness(), apply = vi.fn(async (_config: import('./workbook-pivot').PivotConfig, _request: import('@sheets-web/xlsx-engine/pivot-controls').PivotControlRequest) => {}), error = vi.fn()
  let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { canEdit: () => true, apply, error }, 'controls') })
  expect(h.ranges).toEqual([[4, 12, 1, 1]])
  expect(h.floats.mock.calls[0]!.slice(1)).toEqual([{ componentKey: 'controls-0', allowTransform: false, eventPassThrough: false }, { width: 320, height: 180 }])
  const inputs = h.host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')
  expect([...inputs].map(input => input.checked)).toEqual([true, false])
  await act(async () => { inputs[1]!.click() })
  await act(async () => { h.host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
  expect(apply).toHaveBeenCalledOnce()
  expect(apply.mock.calls[0]![0].hiddenMembers?.row).toEqual([[]])
  expect(apply.mock.calls[0]![1]).toEqual({ kind: 'slicer', tablePath: view.control.tablePath, field: '地区', name: 'RegionSlicer', caption: '销售地区', anchor: view.control.anchor })
  expect(error).not.toHaveBeenCalled()
  await act(async () => handle.dispose()); h.cleanup()
})

it('rejects protected and stale control events and releases floats and sheet subscriptions', async () => {
  const h = harness(), apply = vi.fn(async (_config: import('./workbook-pivot').PivotConfig, _request: import('@sheets-web/xlsx-engine/pivot-controls').PivotControlRequest) => {}), error = vi.fn(); let editable = true
  let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { canEdit: () => editable, apply, error }, 'protected') })
  editable = false
  const form = h.host.querySelector('form')!
  await act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(apply).not.toHaveBeenCalled(); expect(h.host.textContent).toContain('不可编辑')
  await act(async () => handle.dispose()); handle.dispose()
  await act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(apply).not.toHaveBeenCalled(); expect(h.components.size).toBe(0); expect(h.host.children).toHaveLength(0); expect(h.eventDispose).toHaveBeenCalledOnce()
  h.cleanup()
})

it('hides controls on other sheets and restores their anchor on returning', async () => {
  const h = harness(); let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { canEdit: () => true, apply: async () => {}, error: vi.fn() }, 'sheets') })
  await act(async () => { h.switchSheet('数据'); await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(h.host.textContent).toBe('')
  await act(async () => { h.switchSheet('汇总'); await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(h.host.textContent).toContain('销售地区'); expect(h.ranges).toEqual([[4, 12, 1, 1], [4, 12, 1, 1]])
  await act(async () => handle.dispose()); h.cleanup()
})

it('retains the complete native timeline interval and applies its member selection', async () => {
  const h = harness(), apply = vi.fn(async (_config: import('./workbook-pivot').PivotConfig, _request: import('@sheets-web/xlsx-engine/pivot-controls').PivotControlRequest) => {})
  const dates: PivotControlView = { control: { ...view.control, kind: 'timeline', field: '日期', from: '2026-01-01', to: '2026-01-31' }, pivot: { ...view.pivot, rowFields: ['日期'], hiddenMembers: undefined }, fields: [{ name: '日期', axis: 'row', level: 0, timeline: true, members: [{ value: '46027', date: '2026-01-05' }, { value: '46058', date: '2026-02-05' }] }] }
  let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [dates], { canEdit: () => true, apply, error: vi.fn() }, 'dates') })
  expect([...h.host.querySelectorAll<HTMLInputElement>('input[type=date]')].map(input => input.value)).toEqual(['2026-01-01', '2026-01-31'])
  await act(async () => { h.host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
  expect(apply.mock.calls[0]![0].hiddenMembers?.row).toEqual([['46058']])
  expect(apply.mock.calls[0]![1]).toMatchObject({ from: '2026-01-01', to: '2026-01-31' })
  await act(async () => handle.dispose()); h.cleanup()
})

it('cleans partial layers when native mounting fails and keeps the failure visible', async () => {
  const h = harness(), error = vi.fn()
  h.floats.mockImplementationOnce(() => { throw new Error('mount failed') })
  let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { canEdit: () => true, apply: async () => {}, error }, 'failed') })
  expect(error).toHaveBeenCalledWith('mount failed'); expect(h.components.size).toBe(0)
  await act(async () => handle.dispose()); h.cleanup()
})

it('updates protected state without remounting or discarding pending member choices', async () => {
  const h = harness(); let editable = false, handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { canEdit: () => editable, apply: async () => {}, error: vi.fn() }, 'unlock') })
  const fieldset = h.host.querySelector('fieldset')!
  expect(fieldset.disabled).toBe(true)
  await act(async () => { editable = true; handle.refreshState() })
  expect(fieldset.disabled).toBe(false)
  const west = h.host.querySelectorAll<HTMLInputElement>('input')[1]!
  await act(async () => west.click())
  await act(async () => { editable = false; handle.refreshState() })
  expect(fieldset.disabled).toBe(true)
  await act(async () => { editable = true; handle.refreshState() })
  expect(west.checked).toBe(true); expect(h.floats).toHaveBeenCalledOnce()
  await act(async () => handle.dispose()); h.cleanup()
})

it('follows host transaction locks and restores inputs after unlocking', async () => {
  const h = harness(); h.host.setAttribute('inert', '')
  let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { stateHost: h.host, canEdit: () => !h.host.hasAttribute('inert'), apply: async () => {}, error: vi.fn() }, 'transaction') })
  expect(h.host.querySelector('fieldset')!.disabled).toBe(true)
  await act(async () => { h.host.removeAttribute('inert') })
  expect(h.host.querySelector('fieldset')!.disabled).toBe(false)
  await act(async () => { h.host.setAttribute('inert', '') })
  expect(h.host.querySelector('fieldset')!.disabled).toBe(true)
  await act(async () => handle.dispose()); h.cleanup()
})

it.each(['sheet.mutation.set-worksheet-right-to-left', 'sheet.mutation.set-frozen'])('reanchors %s after the native frame and retains pending choices', async command => {
  const h = harness(); let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], { canEdit: () => true, apply: async () => {}, error: vi.fn() }, 'rtl') })
  await act(async () => h.host.querySelectorAll<HTMLInputElement>('input')[1]!.click())
  await act(async () => { h.command(command); h.command(command); await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(h.floats).toHaveBeenCalledTimes(2)
  expect(h.host.querySelectorAll<HTMLInputElement>('input')[1]!.checked).toBe(true)
  await act(async () => { h.command('sheet.operation.set-selections'); await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(h.floats).toHaveBeenCalledTimes(2)
  await act(async () => handle.dispose())
  expect(h.commandDispose).toHaveBeenCalledOnce()
  await act(async () => { h.command(command); await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(h.host.children).toHaveLength(0); h.cleanup()
})

it('keeps a frozen-anchor control whole across the divider and restores its native layout on disposal', async () => {
  const h = harness(), service = new CanvasFloatDomService()
  const layout: IFloatDomLayout = { startX: 200, endX: 248, startY: 20, endY: 68, width: 320, height: 180, rotate: 0, absolute: { left: true, top: true } }
  const source = new BehaviorSubject(layout)
  const freeze = { startRow: 6, startColumn: 13, ySplit: 6, xSplit: 13 }
  const cell = { startX: 200, startY: 20 }, pane = { isActive: true, left: 40, top: 20, width: 700, height: 500, viewportScrollX: 0, viewportScrollY: 0 }
  const skeleton = { worksheet: { getFreeze: () => freeze }, getCellWithCoordByIndex: () => cell }
  const scene = { getAncestorScale: () => ({ scaleX: 1, scaleY: 1 }), getViewport: () => pane }
  const render = { scene, with: () => ({ getCurrentSkeleton: () => skeleton }), engine: { getCanvasElement: () => ({ clientWidth: 800, clientHeight: 600 }) } }
  const runtime = Object.assign(h.runtime, { univer: { __getInjector: () => ({ get: (token: unknown) => token === CanvasFloatDomService ? service : token === IRenderManagerService ? { getRenderById: () => render } : undefined }) } })
  h.floats.mockImplementationOnce(() => {
    service.addFloatDom({ id: 'owned', unitId: 'book', componentKey: 'test', position$: source, onPointerMove() {}, onPointerDown() {}, onPointerUp() {}, onWheel() {} })
    return { id: 'owned', dispose() {} }
  })
  let handle!: ReturnType<typeof installPivotControlOverlay>
  await act(async () => { handle = installPivotControlOverlay(runtime as unknown as Parameters<typeof installPivotControlOverlay>[0], [view], { canEdit: () => true, apply: async () => {}, error: vi.fn() }, 'freeze') })
  const projected: IFloatDomLayout[] = []
  const subscription = service.domLayers[0]![1].position$.subscribe(value => projected.push(value))
  expect(projected.at(-1)).toMatchObject({ startX: 200, endX: 520, startY: 20, endY: 200 })
  // 原生缩放仍是真值；外框只在网格边缘裁切，不在冻结分隔线处缩短。
  source.next({ ...layout, width: 640, height: 360 })
  expect(projected.at(-1)).toMatchObject({ endX: 740, endY: 380, width: 640, height: 360 })
  cell.startX = 12000; pane.viewportScrollX = 11600
  source.next({ ...layout, absolute: { left: false, top: true } })
  expect(projected.at(-1)).toMatchObject({ startX: 400, endX: 720, absolute: { left: true, top: true } })
  freeze.startRow = 3; freeze.ySplit = 2; source.next(layout)
  expect(projected.at(-1)).toMatchObject({ startY: 20, endY: 68 })
  freeze.ySplit = 0; freeze.xSplit = 0; source.next(layout)
  expect(projected.at(-1)).toBe(layout)
  await act(async () => handle.dispose())
  expect(service.domLayers[0]![1].position$).toBe(source)
  subscription.unsubscribe(); source.complete(); h.cleanup()
})

it('restores unsubmitted selections after a geometry transaction and exposes protected geometry handles', async () => {
  const h = harness(), changeAnchor = vi.fn(async () => {}), key = `${view.control.tablePath}:${view.control.name}`
  let handle!: ReturnType<typeof installPivotControlOverlay>
  const actions = { canEdit: () => false, apply: async () => {}, changeAnchor, error: vi.fn() }
  await act(async () => { handle = installPivotControlOverlay(h.runtime, [view], actions, 'geometry', { [key]: { selected: ['东', '西'], from: '', to: '' } }) })
  expect(h.host.querySelectorAll<HTMLInputElement>('input')[1]!.checked).toBe(true)
  expect(h.host.querySelector<HTMLButtonElement>('[data-control-geometry="move"]')?.disabled).toBe(true)
  expect(h.host.querySelector<HTMLButtonElement>('[data-control-geometry="resize"]')?.disabled).toBe(true)
  expect(handle.snapshotDrafts()[key]?.selected).toEqual(['东', '西'])
  await act(async () => handle.dispose()); h.cleanup()
})
