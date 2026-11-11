import { CommandType, ICommandService, IUndoRedoService, generateRandomId } from '@univerjs/core'
import { formatAddress, formatSheetQualifier, parseRange, type SparklineSpec } from '@sheets-web/xlsx-engine'

export type WorkbookSparklineType = 'line' | 'column' | 'stacked'
export interface WorkbookSparklineGroup {
  type: WorkbookSparklineType
  color?: string
  cells: { cell: string; sourceRef: string }[]
}
export interface WorkbookSparklineOperation extends Record<string, unknown> {
  kind: 'appendSheetSparklines' | 'removeSheetSparklines' | 'editSheetSparklineGroup'
  sheetName: string
  groups?: WorkbookSparklineGroup[]
  targets?: string[]
  target?: string
  type?: WorkbookSparklineType
  color?: string
  negativeColor?: string
}
interface Options {
  readonly?: () => boolean
  protectedSheet?: (sheetId: string) => boolean
  existing?: (sheetId: string) => readonly SparklineSpec[]
  sourceSheetId?: (sourceSheetName: string) => string | undefined
  refresh?: (sheetId: string, specs: readonly SparklineSpec[]) => void
  changed?: () => void
}
interface Entry { id: string; sheetId: string; action: 'add' | 'remove' | 'edit'; group?: WorkbookSparklineGroup; target?: string; updates?: { type?: WorkbookSparklineType; color?: string; negativeColor?: string; markers?: boolean; showAxis?: boolean } }
const MUTATION = 'sheet.mutation.native-sparkline-add'
const absolute = (address: string) => address.replace(/^([A-Z]+)([0-9]+)$/, '$$$1$$$2')
const canonical = (cell: string) => {
  const range = parseRange(cell)
  if (range.startRow !== range.endRow || range.startColumn !== range.endColumn) throw new Error('迷你图宿主必须是单个单元格')
  return formatAddress(range.startRow, range.startColumn)
}

/** 会话只登记新增；读入原生组保持原对象，保存由追加协议保留原 XML。 */
export function installWorkbookSparklines(runtime: any, options: Options = {}) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const journal = new Map<string, Entry>(), owned = new WeakSet<object>()
  let unitId = runtime.univerAPI.getActiveWorkbook()?.getId(), disposed = false, epoch = 0, revision = 0
  const workbook = () => {
    const book = runtime.univerAPI.getActiveWorkbook()
    return book?.getId() === unitId ? book : undefined
  }
  // 原生引用保存的是载入时表名；改名/撤销之后仍须指向原来源身份。
  const sourceSheets = new Map<string, string>()
  const bindSourceSheets = () => {
    sourceSheets.clear()
    for (const sheet of workbook()?.getSheets() ?? []) sourceSheets.set(sheet.getSheetName().toLowerCase(), sheet.getSheetId())
  }
  bindSourceSheets()
  const display = (sheetId: string): readonly SparklineSpec[] => [
    ...(options.existing?.(sheetId) ?? []).filter(spec => ![...journal.values()].some(entry => entry.sheetId === sheetId && entry.action === 'remove' && entry.target === canonical(spec.target))).map(spec => {
      const edit = [...journal.values()].find(entry => entry.sheetId === sheetId && entry.action === 'edit' && entry.target === canonical(spec.target))
      return edit?.updates ? { ...spec, ...(edit.updates.type ? { kind: edit.updates.type === 'stacked' ? 'winLoss' as const : edit.updates.type } : {}), ...(edit.updates.color ? { color: edit.updates.color } : {}), ...(edit.updates.negativeColor ? { negativeColor: edit.updates.negativeColor } : {}), ...(edit.updates.markers !== undefined ? { markers: edit.updates.markers } : {}), ...(edit.updates.showAxis !== undefined ? { showAxis: edit.updates.showAxis } : {}) } : spec
    }),
    ...[...journal.values()].filter(entry => entry.sheetId === sheetId && entry.action === 'add' && entry.group).flatMap(({ group }) => group!.cells.map(cell => ({
      kind: group!.type === 'stacked' ? 'winLoss' as const : group!.type,
      target: cell.cell, source: cell.sourceRef,
      ...(group!.color ? { color: group!.color } : {}),
    }))),
  ]
  const refresh = (sheetId: string) => options.refresh?.(sheetId, display(sheetId))
  const ensureEditable = (sheetId: string) => {
    if (disposed) throw new Error('迷你图编辑已关闭')
    if (options.readonly?.()) throw new Error('只读工作簿不能新增迷你图')
    if (options.protectedSheet?.(sheetId)) throw new Error('工作表受保护，不能新增迷你图')
  }
  const ensureFree = (sheetId: string, group: WorkbookSparklineGroup) => {
    const occupied = new Set(display(sheetId).map(spec => canonical(spec.target)))
    for (const cell of group.cells) {
      if (occupied.has(cell.cell)) throw new Error(`${cell.cell} 已有迷你图，请选择其它源范围`)
      occupied.add(cell.cell)
    }
  }
  const registration = commands.registerCommand({ id: MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (disposed || !params || !owned.has(params) || params.epoch !== epoch || params.unitId !== unitId || !workbook()?.getSheetBySheetId(params.entry.sheetId)) return false
      const entry: Entry = params.entry, previous = journal.get(entry.id)
      if (params.present) {
        ensureEditable(entry.sheetId)
        if (!previous && entry.action === 'add' && entry.group) ensureFree(entry.sheetId, entry.group)
        journal.set(entry.id, entry)
      } else journal.delete(entry.id)
      try { refresh(entry.sheetId); options.changed?.() }
      catch (error) {
        if (previous) journal.set(entry.id, previous)
        else journal.delete(entry.id)
        refresh(entry.sheetId)
        throw error
      }
      revision++
      return true
    },
  })
  // 异步对话框/调用准备后，任何正式 mutation 都使旧计划失效。
  const listener = commands.onCommandExecuted?.((command: any) => { if (command.type === CommandType.MUTATION) revision++ })
  const prepare = (type: WorkbookSparklineType, color?: string) => {
    const book = workbook(), sheet = book?.getActiveSheet(), range = book?.getActiveRange()?.getRange()
    if (!book || !sheet || !range) throw new Error('请先选择当前工作表的数据范围')
    const sheetId = sheet.getSheetId()
    ensureEditable(sheetId)
    if (!['line', 'column', 'stacked'].includes(type)) throw new Error('迷你图类型无效')
    if (color !== undefined && !/^#[0-9a-f]{6}$/i.test(color)) throw new Error('迷你图颜色必须是 #RRGGBB')
    const { startRow, endRow, startColumn, endColumn } = range
    if (![startRow, endRow, startColumn, endColumn].every(Number.isInteger) || startRow < 0 || startColumn < 0 || endRow < startRow || endRow >= Math.min(sheet.getMaxRows(), 1048576)) throw new Error('迷你图源范围无效')
    if (endColumn <= startColumn) throw new Error('迷你图源范围至少需要两列')
    if (endRow - startRow + 1 > 200) throw new Error('一次最多新增 200 行迷你图，请缩小选择范围')
    if (endColumn + 1 >= Math.min(sheet.getMaxColumns(), 16384)) throw new Error('选择右侧没有可用列放置迷你图')
    const group: WorkbookSparklineGroup = { type, ...(color ? { color } : {}), cells: [] }
    for (let row = startRow; row <= endRow; row++) group.cells.push({ cell: formatAddress(row, endColumn + 1), sourceRef: `${formatAddress(row, startColumn)}:${formatAddress(row, endColumn)}` })
    ensureFree(sheetId, group)
    const capturedRevision = revision, capturedEpoch = epoch, name = sheet.getSheetName(), sheetModel = sheet.getSheet()
    let committed = false
    return { commit(): boolean {
      ensureEditable(sheetId)
      const active = workbook(), activeSheet = active?.getActiveSheet(), current = active?.getActiveRange()?.getRange()
      if (committed || capturedEpoch !== epoch || capturedRevision !== revision || activeSheet?.getSheetId() !== sheetId || activeSheet?.getSheet() !== sheetModel || activeSheet?.getSheetName() !== name || !current || ['startRow', 'endRow', 'startColumn', 'endColumn'].some(key => current[key] !== range[key])) throw new Error('迷你图目标已变化，请重新选择后操作')
      ensureFree(sheetId, group)
      const entry: Entry = { id: generateRandomId(), sheetId, action: 'add', group }
      const mutation = (present: boolean) => {
        const params = { unitId, entry, present, epoch }
        owned.add(params)
        return { id: MUTATION, params }
      }
      const redo = mutation(true), undo = mutation(false)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('迷你图新增未执行')
      history.pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      committed = true
      return true
    } }
  }
  return {
    prepare,
    add: (type: WorkbookSparklineType, color?: string) => prepare(type, color).commit(),
    remove: () => {
      const book = workbook(), sheet = book?.getActiveSheet(), range = book?.getActiveRange()?.getRange()
      if (!sheet || !range || range.startRow !== range.endRow || range.startColumn !== range.endColumn) throw new Error('请选择一个迷你图宿主单元格')
      const sheetId = sheet.getSheetId(), target = formatAddress(range.startRow, range.startColumn)
      ensureEditable(sheetId)
      if (!(options.existing?.(sheetId) ?? []).some(spec => canonical(spec.target) === target) && ![...journal.values()].some(entry => entry.sheetId === sheetId && entry.action === 'add' && entry.group?.cells.some(cell => canonical(cell.cell) === target))) throw new Error('所选单元格没有迷你图')
      const added = [...journal.values()].find(entry => entry.sheetId === sheetId && entry.action === 'add' && entry.group?.cells.some(cell => canonical(cell.cell) === target))
      const entry: Entry = added ?? { id: generateRandomId(), sheetId, action: 'remove', target }
      const mutation = (present: boolean) => {
        const params = { unitId, entry, present, epoch }
        owned.add(params)
        return { id: MUTATION, params }
      }
      const redo = mutation(added ? false : true), undo = mutation(added ? true : false)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('迷你图删除未执行')
      history.pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      return true
    },
    edit: (updates: { type?: WorkbookSparklineType; color?: string; negativeColor?: string; markers?: boolean; showAxis?: boolean }) => {
      const book = workbook(), sheet = book?.getActiveSheet(), range = book?.getActiveRange()?.getRange()
      if (!sheet || !range || range.startRow !== range.endRow || range.startColumn !== range.endColumn) throw new Error('请选择一个迷你图宿主单元格')
      const sheetId = sheet.getSheetId(), target = formatAddress(range.startRow, range.startColumn)
      ensureEditable(sheetId)
      if (!Object.keys(updates).length) throw new Error('至少指定一个迷你图组属性')
      if (!(options.existing?.(sheetId) ?? []).some(spec => canonical(spec.target) === target)) throw new Error('所选单元格没有原生迷你图')
      const entry: Entry = { id: generateRandomId(), sheetId, action: 'edit', target, updates }
      const mutation = (present: boolean) => { const params = { unitId, entry, present, epoch }; owned.add(params); return { id: MUTATION, params } }
      const redo = mutation(true), undo = mutation(false)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('迷你图编辑未执行')
      history.pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      return true
    },
    display,
    operations(): WorkbookSparklineOperation[] {
      const book = workbook(), groups = new Map<string, WorkbookSparklineGroup[]>()
      const removals = new Map<string, string[]>()
      const operations: WorkbookSparklineOperation[] = []
      for (const entry of journal.values()) {
        const name = book?.getSheetBySheetId(entry.sheetId)?.getSheetName()
        if (!name) continue // 删除工作表后不签发；撤销删页时仍按稳定身份恢复。
        if (entry.action === 'remove' && entry.target) {
          removals.set(name, [...(removals.get(name) ?? []), entry.target])
          continue
        }
        if (entry.action === 'edit' && entry.target) {
          operations.push({ kind: 'editSheetSparklineGroup', sheetName: name, target: entry.target, ...entry.updates })
          continue
        }
        if (!entry.group) continue
        const group = { ...entry.group, cells: entry.group.cells.map(cell => ({ cell: cell.cell,
          sourceRef: `${formatSheetQualifier(name)}!${cell.sourceRef.split(':').map(absolute).join(':')}` })) }
        groups.set(name, [...(groups.get(name) ?? []), group])
      }
      for (const [sheetName, targets] of removals) operations.push({ kind: 'removeSheetSparklines', sheetName, targets })
      for (const [sheetName, sheetGroups] of groups) {
        let count = 0, batch: WorkbookSparklineGroup[] = []
        for (const group of sheetGroups) {
          if (count + group.cells.length > 200) {
            operations.push({ kind: 'appendSheetSparklines', sheetName, groups: batch })
            batch = []; count = 0
          }
          batch.push(group); count += group.cells.length
        }
        if (batch.length) operations.push({ kind: 'appendSheetSparklines', sheetName, groups: batch })
      }
      return operations
    },
    /** loadOperations 已物化草稿：只清增量，staged 中原操作由 main 保留。 */
    reset() {
      const ids = new Set([...journal.values()].map(entry => entry.sheetId))
      journal.clear(); epoch++; revision++; unitId = runtime.univerAPI.getActiveWorkbook()?.getId()
      bindSourceSheets()
      for (const id of ids) refresh(id)
    },
    assertStructure(command: { id: string; params?: Record<string, any> }, book = workbook()) {
      // 宿主和跨表来源均保护；来源页保守拒绝位移，不影响无关页或普通数值编辑。
      if (!/^sheet\.(?:command|mutation)\.(?:(?:insert|remove)-(?:row|rows|col|cols)(?:-|$)|(?:insert|delete)-range-move-|move-(?:range|rows?|cols?)(?:-|$))/.test(command.id)) return
      const params = command.params ?? {}
      const explicit = [params.subUnitId, params.fromSubUnitId, params.toSubUnitId, params.from?.subUnitId, params.to?.subUnitId].filter(Boolean)
      const ids = new Set(explicit.length ? explicit : [book?.getActiveSheet()?.getSheetId()].filter(Boolean))
      const readsTarget = (hostId: string, spec: SparklineSpec) => {
        const sourceId = spec.sourceSheet === undefined ? hostId
          : options.sourceSheetId?.(spec.sourceSheet) ?? sourceSheets.get(spec.sourceSheet.toLowerCase())
        return sourceId !== undefined && ids.has(sourceId)
      }
      const dependent = (book?.getSheets() ?? []).some((sheet: any) =>
        display(sheet.getSheetId()).some(spec => readsTarget(sheet.getSheetId(), spec)))
      if ([...ids].some(id => display(id).length > 0) || dependent) throw new Error('工作表包含迷你图或是其来源，暂不支持插删或移动行列及单元格；可撤销本次新增后再调整结构')
    },
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true; epoch++; registration.dispose(); listener?.dispose() },
  }
}
