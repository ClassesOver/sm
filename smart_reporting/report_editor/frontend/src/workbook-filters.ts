import { Styles, Worksheet, type IWorksheetData } from '@univerjs/core'
import { FilterModel, type IAutoFilter, type ICustomFilters } from '@univerjs/sheets-filter'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import type { WorkbookOperation } from './workbook-draft'
import { isHiddenAxisEntry } from './workbook-vendor/core/univer-data'

// 官方 pinned sheets-filter 的 FWorksheet.getFilter()/FFilter 投影。
// 条件形状与桥 sheetFilterCriteriaSchema 对齐：colId 为范围首列起的偏移。
// dateGroups（OOXML dateGroupItem 日期分组）是 server 路径独有：pinned
// @univerjs/sheets-filter 0.25.1 的 IFilterColumn 没有 dateGroups 字段，网格
// 既读不到也不会产生该条件，因此这里不映射；含 dateGroups 的源筛选在差分前
// 直接拒绝（与旧 readOnlyReason 行为一致），避免保存时静默丢弃日期分组。
export interface FilterCriteria {
  colId: number
  values?: string[]
  blank?: boolean
  customs?: { and?: boolean; filters: { val: string; operator?: string }[] }
}
export interface FilterRange {
  startRow: number; endRow: number; startColumn: number; endColumn: number
}
export interface FilterCriteriaData {
  colId?: number
  filters?: { blank?: boolean; filters?: string[] }
  customFilters?: { and?: boolean | number; customFilters: { val: string; operator?: string }[] }
}
export interface FilterSheet {
  getSheetId(): string; getSheetName(): string
  getFilter(): {
    getRange(): { getRow(): number; getColumn(): number; getHeight(): number; getWidth(): number }
    getColumnFilterCriteria(column: number): FilterCriteriaData | null | undefined
    /// FFilter.getFilteredOutRows：筛选条件在网格中隐藏的数据行（绝对 0 基）。
    getFilteredOutRows?(): number[]
  } | null
}
export interface FilterWorkbook {
  getId(): string; getWorkbook(): unknown; getSheets(): FilterSheet[]; getSheetBySheetId?(id: string): FilterSheet | null
  /// 快照 rowData.hd（Univer BooleanNumber）：文件加载与手动隐藏的行（0 基键）。缺席＝调用方无法
  /// 读取网格行可见性，v2 可见性声明退回 v1（只写筛选条件）。
  getSnapshot?(): unknown
}

const sameCriteria = (a: FilterCriteria, b: FilterCriteria): boolean =>
  a.colId === b.colId && JSON.stringify({ values: a.values ?? null, blank: a.blank ?? null, customs: a.customs ?? null })
    === JSON.stringify({ values: b.values ?? null, blank: b.blank ?? null, customs: b.customs ?? null })

const sameRows = (a: readonly number[], b: readonly number[]): boolean =>
  a.length === b.length && a.every((row, index) => row === b[index])

// pinned FFilter.getColumnFilterCriteria 返回 FilterColumn.serialize()，其 colId
// 是工作表绝对列号；引擎/桥协议的 colId 是范围首列起的偏移，因此一律用调用方
// 按范围算出的偏移，不能沿用 data.colId（筛选不从 A 列开始时会错位）。
const criteriaOf = (data: FilterCriteriaData, offset: number): FilterCriteria | null => {
  const criteria: FilterCriteria = { colId: offset }
  const values = data.filters?.filters
  if (values?.length) criteria.values = [...values]
  if (data.filters?.blank === true) criteria.blank = true
  const customs = data.customFilters
  if (customs?.customFilters?.length) criteria.customs = { ...(customs.and === 1 || customs.and === true ? { and: true } : {}), filters: customs.customFilters.map(item => ({ val: item.val, ...(item.operator ? { operator: item.operator } : {}) })) }
  if (criteria.values === undefined && criteria.blank === undefined && criteria.customs === undefined) return null
  return criteria
}

const snapshotHiddenRows = (workbook: FilterWorkbook, sheetId: string): Set<number> | undefined => {
  if (!workbook.getSnapshot) return undefined
  const snapshot = workbook.getSnapshot() as {
    sheets?: Record<string, { rowData?: Record<string, { hd?: number | undefined }> | undefined }>
  } | undefined
  const rowData = snapshot?.sheets?.[sheetId]?.rowData
  if (!rowData) return new Set()
  const hidden = new Set<number>()
  for (const [key, row] of Object.entries(rowData)) if (isHiddenAxisEntry(row)) hidden.add(Number(key))
  return hidden
}

/// 可见性声明只覆盖筛选范围的数据行（标题行由引擎固定不动）。
const dataRowsOf = (span: FilterRange): number[] => {
  const rows: number[] = []
  for (let row = span.startRow + 1; row <= span.endRow; row += 1) rows.push(row)
  return rows
}

const hiddenRowsWithin = (hidden: ReadonlySet<number>, span: FilterRange): number[] =>
  dataRowsOf(span).filter(row => hidden.has(row))

const sourceHiddenRows = (model: WorkbookModel, sheetName: string, span: FilterRange): number[] => {
  const hidden = new Set(
    (model.sheets.find(item => item.name === sheetName)?.rows ?? [])
      .filter(row => row.hidden).map(row => row.row - 1),
  )
  return hiddenRowsWithin(hidden, span)
}

/// 源筛选无法由网格无损承载：不可写回结构（readOnlyReason）或 dateGroups
/// （pinned IFilterColumn 无该字段）。这类筛选不灌入网格，也不参与差分。
const gridCannotCarry = (source: NonNullable<WorkbookModel['sheets'][number]['filter']>): boolean =>
  !!source.readOnlyReason || !source.range || source.columns.some(column => column.dateGroups !== undefined)

export const FILTER_RESOURCE = 'SHEET_FILTER_PLUGIN'

/** 加载时把源筛选灌入网格（pinned sheets-filter 的 SHEET_FILTER_PLUGIN 快照资源，
 *  同 withWorkbookNotes 的 SHEET_NOTE_PLUGIN 方式）：范围、条件（colId 转为绝对列）
 *  及 cachedFilteredOut（文件中范围内已隐藏的数据行，保持初始可见性）。
 *  可由原生条件解释的源隐藏只放入filter cache，不能同时保留为人工hd，
 *  否则之后修改条件也无法重新显示；匹配条件却隐藏的源行保留人工hd。
 *  否则 getFilter() 加载后即为 null，保存无关修改时会被差分误判为"移除筛选"。 */
export function withWorkbookFilters<T extends { sheets: Record<string, { id: string; name: string }> }>(data: T, model: WorkbookModel): T {
  const resource: Record<string, unknown> = {}
  for (const sheet of Object.values(data.sheets)) {
    const source = model.sheets.find(item => item.name === sheet.name)?.filter
    if (!source || gridCannotCarry(source)) continue
    const span = source.range!
    const range: FilterRange = { startRow: span.startRow, endRow: span.endRow, startColumn: span.startColumn, endColumn: span.endColumn }
    const state: IAutoFilter = {
      ref: range,
      filterColumns: source.columns.map(column => ({
        colId: range.startColumn + column.colId,
        ...(column.values !== undefined || column.blank ? { filters: { ...(column.blank ? { blank: true } : {}), ...(column.values?.length ? { filters: [...column.values] } : {}) } } : {}),
        ...(column.customs ? { customFilters: { ...(column.customs.and ? { and: 1 } : {}), customFilters: column.customs.filters.map(item => ({ ...item })) as ICustomFilters['customFilters'] } } : {}),
      })),
      cachedFilteredOut: sourceHiddenRows(model, sheet.name, range),
    }
    const snapshot = sheet as unknown as Partial<IWorksheetData>
    // 仅完整加载cellData的实际网格可做分类；轻量资源投影调用方保持原行为。
    if (snapshot.cellData && snapshot.rowData && state.cachedFilteredOut?.length) {
      const styles = new Styles((data as T & { styles?: ConstructorParameters<typeof Styles>[0] }).styles)
      const worksheet = new Worksheet('source-filter-visibility', snapshot, styles)
      const calculated = FilterModel.deserialize('source-filter-visibility', sheet.id, worksheet, { ref: state.ref, filterColumns: state.filterColumns })
      try {
        for (const row of state.cachedFilteredOut) if (calculated.filteredOutRows.has(row) && snapshot.rowData[row]) delete snapshot.rowData[row]!.hd
      } finally { calculated.dispose() }
    }
    resource[sheet.id] = state
  }
  if (!Object.keys(resource).length) return data
  const existing = (data as T & { resources?: { name: string; data: string }[] }).resources ?? []
  return Object.assign(data, { resources: [...existing.filter(item => item.name !== FILTER_RESOURCE), { name: FILTER_RESOURCE, data: JSON.stringify(resource) }] })
}

/** 声明式筛选快照差分（同源 NOTE_MUTATIONS/save 配方）：范围与条件集整体对比，
 *  行可见性 v2 一并落盘：网格筛选隐藏行（getFilteredOutRows）与快照 rowData
 *  隐藏行（文件加载 + 手动隐藏）的并集，以 hiddenRows/visibilityRange 声明式
 *  写回（列出的行隐藏、范围内其余行取消隐藏）。无快照读取能力时可见性退回 v1
 *  （不写行状态）。 */
export function workbookFilterOperations(model: WorkbookModel, workbook: FilterWorkbook | null): WorkbookOperation[] {
  const operations: WorkbookOperation[] = []
  for (const sheet of workbook?.getSheets() ?? []) {
    const source = model.sheets.find(item => item.name === sheet.getSheetName())?.filter
    // 简化测试替身可能未实现筛选 facade；未注册筛选插件的 Univer 实例上
    // getFilter 会因服务缺失抛错（同 notes 的 getNotes 防御）——两者都按
    // "无法读取筛选"跳过，差分退回不产生筛选操作。
    if (typeof sheet.getFilter !== 'function') continue
    let live: ReturnType<NonNullable<FilterSheet['getFilter']>>
    try {
      live = sheet.getFilter()
    } catch {
      continue
    }
    if (source && gridCannotCarry(source)) {
      // 未灌入网格的源筛选：网格里没有筛选＝用户未触碰，原样保留文件中的筛选，
      // 不影响无关修改的保存。网格里出现了筛选（命令守卫之外的路径）则如实拒绝，
      // 而不是覆盖掉无法表示的条件。
      if (!live) continue
      if (source.readOnlyReason) throw new Error(source.readOnlyReason)
      throw new Error(source.range
        ? '筛选含日期分组条件，网格暂不能编辑回写（仅服务端路径可写 dateGroups）'
        : '筛选范围无法解析，网格暂不能编辑回写')
    }
    const snapshotHidden = workbook ? snapshotHiddenRows(workbook, sheet.getSheetId()) : undefined
    if (!live) {
      if (!source) continue
      // 移除筛选后网格重新显示其曾隐藏的行；以模型范围声明网格可见性，
      // 保留 rowData 手动隐藏、取消筛选缓存的隐藏行。无法读取快照时退回 v1。
      const span = source.range
      if (span && snapshotHidden) {
        const range: FilterRange = { startRow: span.startRow, endRow: span.endRow, startColumn: span.startColumn, endColumn: span.endColumn }
        const hidden = hiddenRowsWithin(snapshotHidden, range)
        if (!sameRows(hidden, sourceHiddenRows(model, sheet.getSheetName(), range))) {
          operations.push({ kind: 'applySheetFilter', sheetName: sheet.getSheetName(), filter: null, hiddenRows: hidden, visibilityRange: range })
          continue
        }
      }
      operations.push({ kind: 'applySheetFilter', sheetName: sheet.getSheetName(), filter: null })
      continue
    }
    const bounds = live.getRange()
    const range: FilterRange = {
      startRow: bounds.getRow(), endRow: bounds.getRow() + bounds.getHeight() - 1,
      startColumn: bounds.getColumn(), endColumn: bounds.getColumn() + bounds.getWidth() - 1,
    }
    const columns: FilterCriteria[] = []
    for (let column = range.startColumn; column <= range.endColumn; column += 1) {
      const data = live.getColumnFilterCriteria(column)
      if (!data) continue
      const criteria = criteriaOf(data, column - range.startColumn)
      if (criteria) columns.push(criteria)
    }
    // 网格隐藏行 = 筛选缓存（getFilteredOutRows）∪ 快照 rowData 隐藏；
    // 两者皆不可读取时可见性退回 v1（不写行状态）。
    const liveHidden = snapshotHidden !== undefined || live.getFilteredOutRows
      ? hiddenRowsWithin(new Set([...(snapshotHidden ?? []), ...(live.getFilteredOutRows?.() ?? [])]), range)
      : undefined
    const unchanged = source && source.range
      && source.range.startRow === range.startRow && source.range.endRow === range.endRow
      && source.range.startColumn === range.startColumn && source.range.endColumn === range.endColumn
      && source.columns.length === columns.length
      && source.columns.every((column, index) => {
        const ordered = [...columns].sort((a, b) => a.colId - b.colId)[index]!
        return sameCriteria({ colId: column.colId, values: column.values, blank: column.blank, customs: column.customs }, ordered)
      })
      && (liveHidden === undefined || sameRows(liveHidden, sourceHiddenRows(model, sheet.getSheetName(), range)))
    if (unchanged) continue
    const operation: WorkbookOperation = { kind: 'applySheetFilter', sheetName: sheet.getSheetName(), filter: { range, columns } }
    if (liveHidden) operation.hiddenRows = liveHidden
    operations.push(operation)
  }
  return operations
}
