import { ICommandService } from '@univerjs/core'
import type { WorkbookOperation } from './workbook-draft'
import type { WorkbookModel, OutlineLineEdit } from '@sheets-web/xlsx-engine'
export type OutlineAction = 'group' | 'ungroup' | 'hide-detail' | 'show-detail' | 'clear'
export type OutlineAxis = 'rows' | 'cols'
const KEY = 'genofficeOutline'
type Entry = { level: number; collapsed: boolean }
const manager = (sheet: any, axis: OutlineAxis) =>
  axis === 'rows' ? sheet.getSheet().getRowManager() : sheet.getSheet().getColumnManager()
const data = (sheet: any, axis: OutlineAxis): Record<number, any> =>
  axis === 'rows' ? manager(sheet, axis).getRowData() : manager(sheet, axis).getColumnData()
const read = (sheet: any, axis: OutlineAxis) =>
  new Map<number, Entry>(
    Object.entries(data(sheet, axis)).flatMap(([index, value]) =>
      value?.custom?.[KEY] ? [[Number(index), value.custom[KEY]]] : []
    )
  )
const put = (sheet: any, axis: OutlineAxis, index: number, entry: Entry) => {
  const m = manager(sheet, axis)
  if (axis === 'rows') m.getRowOrCreate(index)
  else m.getColumnOrCreate(index)
  m.setCustomMetadata(index, { ...m.getCustomMetadata(index), [KEY]: entry })
}
export type OutlineGroup = { start: number; end: number; summary: number; level: number; folded: boolean; collapsed: boolean }
function groups(entries: Map<number, Entry>, after: boolean, hidden: (index: number) => boolean = () => false) {
  const result: OutlineGroup[] = []
  const indexes = [...entries.keys()].sort((a, b) => a - b)
  for (let level = 1; level <= 7; level++) {
    let start = -1,
      end = -1
    const close = () => {
      if (start >= 0) {
        const summary = after ? end + 1 : start - 1
        let collapsed = true
        for (let index = start; index <= end && collapsed; index++) collapsed = hidden(index)
        result.push({ start, end, summary, level, folded: entries.get(summary)?.collapsed === true, collapsed })
      }
      start = -1
    }
    for (const index of indexes) {
      if (entries.get(index)!.level < level) continue
      if (start >= 0 && index === end + 1) {
        end = index
        continue
      }
      close()
      start = index
      end = index
    }
    close()
  }
  return result
}
// 读取实际隐藏状态，区分外层折叠与用户显式折叠的内层组。
const lineVisible = (sheet: any, axis: OutlineAxis, index: number): boolean =>
  axis === 'rows' ? sheet.getSheet().getRowRawVisible(index) : sheet.getSheet().getColVisible(index)
export function readWorkbookOutlineSummary(sheet: any): {summaryBelow: boolean; summaryRight: boolean} {
  const settings = sheet.getSheet().getCustomMetadata()?.[KEY]
  return {summaryBelow: settings?.summaryBelow !== false, summaryRight: settings?.summaryRight !== false}
}
export function readWorkbookOutline(sheet: any) {
  const rows = read(sheet, 'rows'), cols = read(sheet, 'cols')
  const {summaryBelow, summaryRight} = readWorkbookOutlineSummary(sheet)
  const signature = (axis: OutlineAxis, entries: Map<number, Entry>) =>
    [...entries].sort(([a], [b]) => a - b).map(([index, entry]) =>
      [index, entry.level, entry.collapsed, lineVisible(sheet, axis, index)])
  return { rows, cols, summaryBelow, summaryRight,
    version: JSON.stringify([summaryBelow, summaryRight, signature('rows', rows), signature('cols', cols)]) }
}
export function workbookOutlineGroups(sheet: any, axis: OutlineAxis): OutlineGroup[] {
  const state = readWorkbookOutline(sheet)
  return groups(state[axis], axis === 'rows' ? state.summaryBelow : state.summaryRight,
    (index) => !lineVisible(sheet, axis, index))
}
function activeSheet(runtime: any, protectedSheet: (id: string) => boolean) {
  const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
  if (!sheet) throw new Error('请先选择工作表')
  if (protectedSheet(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
  return sheet
}
function visibility(sheet: any, axis: OutlineAxis, start: number, end: number, hidden: boolean) {
  const count = Math.min(end, (axis === 'rows' ? sheet.getMaxRows() : sheet.getMaxColumns()) - 1) - start + 1
  if (start < 0 || count <= 0) return
  if (axis === 'rows') {
    if (hidden) sheet.hideRows(start, count)
    else sheet.showRows(start, count)
  } else if (hidden) sheet.hideColumns(start, count)
  else sheet.showColumns(start, count)
}
const outcome = (changed: boolean) => ({ changed, message: changed ? '分组设置已更新，修改尚未保存。' : '所选区域没有可操作的分组。' })
export function toggleWorkbookOutlineGroup(runtime: any, axis: OutlineAxis, target: OutlineGroup,
  collapsed: boolean, protectedSheet: (id: string) => boolean = () => false) {
  const sheet = activeSheet(runtime, protectedSheet), all = workbookOutlineGroups(sheet, axis)
  const group = all.find((g) => g.level === target.level && g.start === target.start && g.end === target.end && g.summary === target.summary)
  if (!group) return outcome(false)
  visibility(sheet, axis, group.start, group.end, collapsed)
  if (!collapsed) for (const nested of all.filter((g) => g.level > group.level && g.start >= group.start &&
    g.end <= group.end && g.summary !== group.summary && g.folded)) visibility(sheet, axis, nested.start, nested.end, true)
  const limit = axis === 'rows' ? 1048576 : 16384
  if (group.summary >= 0 && group.summary < limit)
    put(sheet, axis, group.summary, { level: read(sheet, axis).get(group.summary)?.level ?? 0, collapsed })
  return outcome(true)
}
export function showWorkbookOutlineLevel(runtime: any, axis: OutlineAxis, level: number,
  protectedSheet: (id: string) => boolean = () => false) {
  const sheet = activeSheet(runtime, protectedSheet)
  if (!Number.isInteger(level) || level < 1 || level > 8) return outcome(false)
  const entries = read(sheet, axis), all = workbookOutlineGroups(sheet, axis)
  // 先显示浅层，再隐藏深层；合并连续行列，避免每行触发一条原生命令。
  for (const hidden of [false, true]) {
    const indexes = [...entries].filter(([, entry]) => entry.level > 0 && (entry.level >= level) === hidden)
      .map(([index]) => index).sort((a, b) => a - b)
    let start = -1, end = -1
    for (const index of indexes) {
      if (start >= 0 && index !== end + 1) { visibility(sheet, axis, start, end, hidden); start = -1 }
      if (start < 0) start = index
      end = index
    }
    if (start >= 0) visibility(sheet, axis, start, end, hidden)
  }
  const summaries = new Map<number, boolean>()
  for (const group of all) {
    if (group.summary < 0 || group.summary >= (axis === 'rows' ? 1048576 : 16384)) continue
    const collapsed = group.level >= level
    if (!summaries.has(group.summary) || !collapsed) summaries.set(group.summary, collapsed)
  }
  for (const [index, collapsed] of summaries) put(sheet, axis, index, { level: entries.get(index)?.level ?? 0, collapsed })
  return outcome(all.length > 0)
}
export function setWorkbookOutlineSummary(runtime: any, summary: { below?: boolean; right?: boolean },
  protectedSheet: (id: string) => boolean = () => false) {
  const sheet = activeSheet(runtime, protectedSheet), state = readWorkbookOutline(sheet)
  const summaryBelow = summary.below ?? state.summaryBelow, summaryRight = summary.right ?? state.summaryRight
  if (summaryBelow === state.summaryBelow && summaryRight === state.summaryRight) return outcome(false)
  const native = sheet.getSheet(), custom = native.getCustomMetadata()
  native.setCustomMetadata({ ...custom, [KEY]: { ...custom?.[KEY], summaryBelow, summaryRight } })
  return outcome(true)
}
export function applyWorkbookOutline(
  runtime: any,
  action: OutlineAction,
  axisChoice: OutlineAxis | 'auto' = 'auto',
  protectedSheet: (id: string) => boolean = () => false
): { changed: boolean; message: string } {
  const workbook = runtime.univerAPI.getActiveWorkbook(),
    sheet = workbook?.getActiveSheet(),
    range = workbook?.getActiveRange() ?? (action === 'clear' ? {
      getRow: () => 0, getColumn: () => 0, getHeight: () => 1, getWidth: () => 1
    } : undefined)
  if (!sheet || !range) throw new Error('请先选择需要分组的区域')
  if (protectedSheet(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
  const axis: OutlineAxis =
    axisChoice === 'auto'
      ? range.getHeight() >= sheet.getMaxRows() && range.getWidth() < sheet.getMaxColumns()
        ? 'cols'
        : 'rows'
      : axisChoice
  const axes: OutlineAxis[] = action === 'clear' ? ['rows', 'cols'] : [axis]
  let changed = false
  for (const current of axes) {
    const entries = read(sheet, current),
      start = current === 'rows' ? range.getRow() : range.getColumn(),
      end = start + (current === 'rows' ? range.getHeight() : range.getWidth()) - 1
    const settings = sheet.getSheet().getCustomMetadata()?.[KEY],
      after = current === 'rows' ? settings?.summaryBelow !== false : settings?.summaryRight !== false
    const all = groups(entries, after)
    const visible = (i: number) =>
      current === 'rows' ? sheet.getSheet().getRowRawVisible(i) : sheet.getSheet().getColVisible(i)
    const hide = (from: number, to: number, hidden: boolean) => {
      const count = Math.min(to, (current === 'rows' ? sheet.getMaxRows() : sheet.getMaxColumns()) - 1) - from + 1
      if (count <= 0) return
      if (current === 'rows') {
        if (hidden) sheet.hideRows(from, count)
        else sheet.showRows(from, count)
      } else if (hidden) sheet.hideColumns(from, count)
      else sheet.showColumns(from, count)
    }
    if (action === 'group' || action === 'ungroup') {
      for (let i = start; i <= end; i++) {
        const old = entries.get(i) ?? { level: 0, collapsed: false },
          level = Math.min(7, Math.max(0, old.level + (action === 'group' ? 1 : -1)))
        if (level !== old.level) {
          put(sheet, current, i, { ...old, level })
          changed = true
        }
      }
    } else if (action === 'clear') {
      const whole = range.getHeight() === 1 && range.getWidth() === 1
      for (const [index, entry] of entries) {
        if (!whole && (index < start || index > end)) continue
        if (all.some((g) => g.start <= index && g.end >= index && !visible(index))) hide(index, index, false)
        if (entry.level || entry.collapsed) {
          put(sheet, current, index, { level: 0, collapsed: false })
          changed = true
        }
      }
    } else {
      const group = all
        .filter((g) => (g.start <= end && g.end >= start) || (g.summary >= start && g.summary <= end))
        .sort((a, b) => b.level - a.level)[0]
      if (!group) continue
      toggleWorkbookOutlineGroup(runtime, current, group, action === 'hide-detail', protectedSheet)
      changed = true
    }
  }
  return {
    changed,
    message: changed
      ? '分组设置已更新，修改尚未保存。'
      : action === 'group'
        ? '已达到最大分组层级。'
        : '所选区域没有可操作的分组。'
  }
}
export function workbookOutlineOperations(baseline: WorkbookModel, workbook: any): WorkbookOperation[] {
  const result: WorkbookOperation[] = []
  for (const sheet of workbook.getSheets()) {
    const before = baseline.sheets.find((item) => item.name === sheet.getSheetName())
    const updates: { rows: OutlineLineEdit[]; columns: OutlineLineEdit[] } = { rows: [], columns: [] }
    for (const axis of ['rows', 'cols'] as const) {
      const live = read(sheet, axis),
        original = new Map<number, { level: number; collapsed: boolean; hidden: boolean }>()
      const sourceFilter = axis === 'rows' ? before?.filter : undefined
      const filterRange = sourceFilter?.range && !sourceFilter.readOnlyReason &&
        !sourceFilter.columns.some(column => column.dateGroups !== undefined) ? sourceFilter.range : undefined
      if (axis === 'rows')
        for (const row of before?.rows ?? [])
          original.set(row.row - 1, {
            level: row.outlineLevel ?? 0,
            collapsed: row.collapsed ?? false,
            hidden: row.hidden
          })
      else
        for (const col of before?.columns ?? [])
          for (let i = col.start - 1; i < col.end; i++)
            original.set(i, { level: col.outlineLevel ?? 0, collapsed: col.collapsed ?? false, hidden: col.hidden })
      const indexes = new Set([
        ...original.keys(),
        ...live.keys(),
        ...Object.keys(data(sheet, axis)).map(Number)
      ])
      for (const index of indexes) {
        const old = original.get(index) ?? { level: 0, collapsed: false, hidden: false },
          next = live.get(index) ?? { level: 0, collapsed: false }
        // 源筛选数据区的可见性由 applySheetFilter 声明；raw hidden 不含筛选缓存，不能与文件 hidden 直接差分。
        const hidden = filterRange && index > filterRange.startRow && index <= filterRange.endRow ? undefined
          : axis === 'cols' ? !sheet.getSheet().getColVisible(index) : !sheet.getSheet().getRowRawVisible(index)
        if (
          old.level !== next.level ||
          old.collapsed !== next.collapsed ||
          (hidden !== undefined && old.hidden !== hidden)
        )
          updates[axis === 'rows' ? 'rows' : 'columns'].push({
            index,
            ...next,
            ...(hidden !== undefined ? { hidden } : {})
          })
      }
    }
    const settings = readWorkbookOutline(sheet)
    const summaryChanged = settings.summaryBelow !== (before?.outlineSummaryBelow !== false) ||
      settings.summaryRight !== (before?.outlineSummaryRight !== false)
    if (updates.rows.length || updates.columns.length || summaryChanged)
      result.push({ kind: 'applySheetOutline', sheetName: sheet.getSheetName(), ...updates,
        ...(summaryChanged ? { summaryBelow: settings.summaryBelow, summaryRight: settings.summaryRight } : {}) })
  }
  return result
}

// 原生结构操作移动custom；插入在分组内部时按固定源补min(上方,下方)层级。
export function installWorkbookOutline(runtime: any): { dispose(): void } {
  const commands = runtime.univer.__getInjector().get(ICommandService)
  return commands.onCommandExecuted((command: any) => {
    const axis =
      command.id === 'sheet.mutation.insert-row' ? 'rows' : command.id === 'sheet.mutation.insert-col' ? 'cols' : null
    if (!axis) return
    const params = command.params,
      workbook = runtime.univerAPI.getActiveWorkbook()
    if (!params?.range || params.trigger === 'univer.command.undo' || workbook?.getId() !== params.unitId) return
    const sheet = workbook.getSheetBySheetId(params.subUnitId)
    if (!sheet) return
    const start = axis === 'rows' ? params.range.startRow : params.range.startColumn,
      end = axis === 'rows' ? params.range.endRow : params.range.endColumn
    const entries = read(sheet, axis),
      level = Math.min(entries.get(start - 1)?.level ?? 0, entries.get(end + 1)?.level ?? 0)
    for (let index = start; level > 0 && index <= end; index++)
      if (!entries.has(index)) put(sheet, axis, index, { level, collapsed: false })
  })
}
