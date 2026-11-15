import { createElement as h, useState, useSyncExternalStore, type ComponentType } from 'react'
import { SetFrozenMutation, SetWorksheetRightToLeftMutation } from '@univerjs/sheets'
import type { Univer } from '@univerjs/core'
import { installPivotControlLayout } from './workbook-pivot-control-layout'
import { installPivotControlGeometry, type PivotControlAnchor } from './workbook-pivot-control-geometry'
import { readPivotControls, upsertPivotControlRequestSchema, type PivotControl, type PivotControlRequest } from '@sheets-web/xlsx-engine/pivot-controls'
import { readWorkbookPivots, type PivotConfig, type WorkbookPivot } from './workbook-pivot'
import { readPivotFilterFields, pivotFilterHiddenMembers, pivotMemberFilterConfig, pivotTimelineFilterConfig, type PivotFilterField } from './workbook-pivot-filters'
import './workbook-pivot-controls.css'

export interface PivotControlView { control: PivotControl; pivot: WorkbookPivot; fields: PivotFilterField[] }
interface Disposable { dispose(): void }
interface ControlSheet<R> {
  getSheetName(): string
  getRange(row: number, column: number, rows: number, columns: number): R
  addFloatDomToRange(range: R, layer: { componentKey: string; allowTransform: boolean; eventPassThrough: boolean }, layout: { width: number; height: number }): (Disposable & { id?: string }) | null | undefined | void
}
interface ControlRuntime<R> { univer?: Pick<Univer, '__getInjector'>; univerAPI: {
  registerComponent(key: string, component: ComponentType): Disposable
  getActiveWorkbook(): { getActiveSheet(): ControlSheet<R> | null | undefined } | null | undefined
  Event: { ActiveSheetChanged: string }
  addEvent(event: string, callback: () => void): Disposable
  onCommandExecuted(callback: (command: { id: string }) => void): Disposable
} }
interface ControlActions {
  stateHost?: HTMLElement
  canEdit(view: PivotControlView): boolean
  apply(config: PivotConfig, request: PivotControlRequest): Promise<void>
  changeAnchor?(view: PivotControlView, anchor: PivotControlAnchor): Promise<void>
  error(message: string): void
}
/** 只投影通过引擎完整所有权校验的原生控件，外部控件不能冒充本地可编辑控件。 */
export async function readPivotControlViews(bytes: Uint8Array): Promise<PivotControlView[]> {
  const controls = await readPivotControls(bytes)
  if (!controls.length) return []
  const pivots = await readWorkbookPivots(bytes), fields = new Map<string, PivotFilterField[]>(), result: PivotControlView[] = []
  for (const control of controls) {
    const pivot = pivots.find(pivot => pivot.tablePath === control.tablePath)
    if (!pivot || pivot.readonlyReason) throw new Error(pivot?.readonlyReason ?? '原生控件的透视表已变化')
    if (!fields.has(pivot.tablePath)) fields.set(pivot.tablePath, await readPivotFilterFields(bytes, pivot))
    result.push({ control, pivot, fields: fields.get(pivot.tablePath)! })
  }
  return result
}

interface ControlDraft { selected: string[]; from: string; to: string }
export type PivotControlDrafts = Record<string, ControlDraft>
type Geometry = { start?: ReturnType<typeof installPivotControlGeometry>['start'] }
function controlComponent(view: PivotControlView, draft: ControlDraft, actions: ControlActions, active: () => boolean, subscribe: (listener: () => void) => () => void, geometry: Geometry): ComponentType {
  const { control, pivot, fields } = view, field = fields.find(field => field.name === control.field)!
  let pending = false
  return function PivotControlPanel() {
    const editable = useSyncExternalStore(subscribe, () => actions.canEdit(view), () => false)
    const [selected, setSelected] = useState(draft.selected)
    const [from, setFrom] = useState(draft.from), [to, setTo] = useState(draft.to)
    const [busy, setBusy] = useState(false), [error, setError] = useState('')
    const submit = async () => {
      if (!active() || pending) return
      pending = true; setBusy(true); setError('')
      try {
        if (!actions.canEdit(view)) throw new Error('当前控件不可编辑，请检查工作表保护或保存状态')
        const config = control.kind === 'slicer' ? pivotMemberFilterConfig(pivot, fields, field.name, selected) : pivotTimelineFilterConfig(pivot, fields, field.name, from, to)
        const request: PivotControlRequest = { kind: control.kind, tablePath: control.tablePath, field: control.field, name: control.name, ...(control.caption !== undefined ? { caption: control.caption } : {}), ...(control.anchor ? { anchor: control.anchor } : {}), ...(control.kind === 'timeline' ? { from, to } : {}) }
        await actions.apply(config, request)
      } catch (reason) {
        const message = (reason as Error).message
        if (active()) { setError(message); actions.error(message) }
      } finally { pending = false; if (active()) setBusy(false) }
    }
    return h('form', { className: 'workbook-pivot-control', 'aria-label': `${control.kind === 'slicer' ? '切片器' : '时间线'}：${control.caption ?? field.name}`, 'data-pivot-control': control.name,
      onSubmit: event => { event.preventDefault(); void submit() }, onPointerDown: event => event.stopPropagation(), onKeyDown: event => event.stopPropagation(), onWheel: event => event.stopPropagation(),
    }, h('div', { className: 'workbook-pivot-control-header' }, h('strong', { className: 'workbook-pivot-control-title' }, control.caption ?? field.name), actions.changeAnchor ? h('button', { type: 'button', 'data-control-geometry': 'move', 'aria-label': '移动控件', title: '拖动以移动，松开后吸附到单元格', disabled: busy || !editable, onPointerDown: event => geometry.start?.(event.nativeEvent, event.currentTarget, 'move') }, '移动') : null),
    h('fieldset', { disabled: busy || !editable },
      control.kind === 'slicer' ? h('div', { className: 'workbook-pivot-control-members' }, ...field.members.map(member => h('label', { key: member.value }, h('input', { type: 'checkbox', checked: selected.includes(member.value), onChange: event => { draft.selected = event.target.checked ? [...draft.selected, member.value] : draft.selected.filter(value => value !== member.value); setSelected(draft.selected) } }), member.value || '（空白）'))) : h('div', { className: 'workbook-pivot-control-dates' },
        h('label', null, '开始日期', h('input', { type: 'date', 'aria-label': '开始日期', value: from, onChange: event => { draft.from = event.target.value; setFrom(draft.from) } })),
        h('label', null, '结束日期', h('input', { type: 'date', 'aria-label': '结束日期', value: to, onChange: event => { draft.to = event.target.value; setTo(draft.to) } }))),
      h('div', { className: 'workbook-pivot-control-actions' }, control.kind === 'slicer' ? h('button', { type: 'button', onClick: () => { draft.selected = field.members.map(member => member.value); setSelected(draft.selected) } }, '全选') : null, h('button', { type: 'submit' }, busy ? '应用中…' : '应用筛选'))),
    error ? h('p', { role: 'alert' }, error) : null,
    actions.changeAnchor ? h('button', { type: 'button', className: 'workbook-pivot-control-resize', 'data-control-geometry': 'resize', 'aria-label': '调整控件尺寸', title: '拖动以调整尺寸，Esc 取消', disabled: busy || !editable, onPointerDown: event => geometry.start?.(event.nativeEvent, event.currentTarget, 'resize') }, '↘') : null)
  }
}

/** 几何只提交现有原生控件操作，不把未应用的成员/日期输入意外写成筛选。 */
export async function pivotControlGeometryOperation(bytes: Uint8Array, before: PivotControlView, anchor: PivotControlAnchor) {
  const current = (await readPivotControlViews(bytes)).find(view => view.control.tablePath === before.control.tablePath && view.control.name === before.control.name)
  if (!current || JSON.stringify(current) !== JSON.stringify(before)) throw new Error('透视表来源或控件已变化，请先刷新透视表')
  const { kind, tablePath, field, name, caption, from, to } = current.control
  const request = upsertPivotControlRequestSchema.parse({ kind, tablePath, field, name, ...(caption !== undefined ? { caption } : {}), ...(from !== undefined ? { from } : {}), ...(to !== undefined ? { to } : {}), anchor })
  return { kind: 'upsertPivotControl' as const, request }
}

/** 会话预览不另存绘图；筛选与几何提交均写回已有 OOXML 控件事务。 */
export function installPivotControlOverlay<R>(runtime: ControlRuntime<R>, views: PivotControlView[], actions: ControlActions, prefix: string, initialDrafts: PivotControlDrafts = {}): Disposable & { refreshState(): void; snapshotDrafts(): PivotControlDrafts } {
  let disposed = false, generation = 0, frame = 0
  const drafts = new Map<string, ControlDraft>(Object.entries(structuredClone(initialDrafts)))
  const listeners = new Set<() => void>()
  const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
  const refreshState = () => { if (!disposed) for (const listener of listeners) listener() }
  const observer = actions.stateHost ? new MutationObserver(refreshState) : undefined
  if (actions.stateHost) observer!.observe(actions.stateHost, { attributes: true, subtree: true, attributeFilter: ['inert'] })
  const layers: Disposable[] = []
  const clear = () => { generation++; for (const layer of layers.splice(0).reverse()) { try { layer.dispose() } catch { /* 工作簿可能已销毁，继续释放注册。 */ } } }
  const refresh = () => {
    clear()
    if (disposed) return
    const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(), current = generation
    if (!sheet) return
    try {
      views.forEach((view, index) => {
        if (view.pivot.targetSheetName !== sheet.getSheetName()) return
        const anchor = view.control.anchor, key = `${prefix}-${index}`
        const field = view.fields.find(field => field.name === view.control.field)
        if (!anchor || !field) throw new Error('原生控件缺少可显示的位置或字段')
        const draftKey = `${view.control.tablePath}:${view.control.name}`, geometry: Geometry = {}
        if (!drafts.has(draftKey)) {
          const hidden = new Set(pivotFilterHiddenMembers(view.pivot, field))
          drafts.set(draftKey, { selected: field.members.filter(member => !hidden.has(member.value)).map(member => member.value), from: view.control.from ?? '', to: view.control.to ?? '' })
        }
        const active = () => !disposed && generation === current
        layers.push(runtime.univerAPI.registerComponent(key, controlComponent(view, drafts.get(draftKey)!, actions, active, subscribe, geometry)))
        const float = sheet.addFloatDomToRange(sheet.getRange(anchor.row, anchor.column, 1, 1), { componentKey: key, allowTransform: false, eventPassThrough: false }, { width: anchor.width ?? (view.control.kind === 'slicer' ? 192 : 480), height: anchor.height ?? (view.control.kind === 'slicer' ? 260 : 160) })
        if (!float) throw new Error('原生控件浮层未能显示，请重新打开工作表')
        layers.push(float)
        if (runtime.univer && float.id) layers.push(installPivotControlLayout(runtime.univer, float.id, anchor))
        if (runtime.univer && float.id && actions.changeAnchor) {
          const controller = installPivotControlGeometry(runtime.univer, float.id, anchor, { canEdit: () => active() && actions.canEdit(view), commit: value => actions.changeAnchor!(view, value), error: actions.error })
          geometry.start = controller.start; layers.push(controller)
        }
      })
    } catch (error) { clear(); actions.error((error as Error).message) }
  }
  const scheduleRefresh = () => {
    if (disposed) return
    clear(); cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => { frame = 0; refresh() })
  }
  const subscription = runtime.univerAPI.addEvent(runtime.univerAPI.Event.ActiveSheetChanged, scheduleRefresh)
  const commands = runtime.univerAPI.onCommandExecuted(command => {
    if (command.id === SetWorksheetRightToLeftMutation.id || command.id === SetFrozenMutation.id) scheduleRefresh()
  })
  refresh()
  return { refreshState, snapshotDrafts: () => structuredClone(Object.fromEntries(drafts)), dispose() { if (disposed) return; disposed = true; observer?.disconnect(); cancelAnimationFrame(frame); subscription.dispose(); commands.dispose(); clear(); listeners.clear(); drafts.clear() } }
}
