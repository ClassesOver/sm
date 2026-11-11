import type { TableAddition, TableEdit, WorkbookModel } from '@sheets-web/xlsx-engine'
import { columnLabel, formatAddress, escapeXmlAttribute, parseRange } from '@sheets-web/xlsx-engine'
import { shiftSpecOf, shiftTablePart } from '@sheets-web/xlsx-engine/structural'
import { structuralMutation } from './workbook-grid-operations'
import type { IUniverSheetsTableConfig } from '@univerjs/sheets-table'
import type { WorkbookOperation } from './workbook-draft'
import { withNativeTableThemes } from './workbook-table-styles'

// 表头文字是列名的文件来源；结构日志已先应用到 baseline，不能重复迁移范围。
export function workbookTableOperations(model: WorkbookModel, workbook: any): WorkbookOperation[] {
  if (!workbook?.getTableList || !workbook?.getSheets) return []
  const edits: TableEdit[] = []
  const additions: TableAddition[] = []
  const newTableEdits: TableEdit[] = []
  const tables = workbook.getTableList()
  for (const sheet of workbook.getSheets()) {
    const source = model.sheets.find(item => item.name === sheet.getSheetName())
    if (source?.tablesReadOnlyReason) continue
    for (const table of tables.filter((table: any) => table.subUnitId === sheet.getSheetId() && table.meta?.nativeCreatedTable === true)) {
      const style = table.meta.nativeTableStyle
      additions.push({ worksheetSheetName: sheet.getSheetName(), area: { ...table.range }, name: table.name,
        columnNames: table.columns.map((column: any) => column.displayName), style: style?.name ?? '', bandedRows: !!style?.showRowStripes,
        ...(table.showHeader === false ? { headerRow: false } : {}) })
      const options = { ...(table.meta.nativeFilterButton === false ? { filterButton: false } : {}), ...(table.meta.nativeTotalsRowCount > 0 ? { totalsRow: true } : {}),
        ...(style?.showFirstColumn ? { firstColumn: true } : {}), ...(style?.showLastColumn ? { lastColumn: true } : {}),
        ...(style?.showColumnStripes ? { bandedColumns: true } : {}) }
      if (Object.keys(options).length) newTableEdits.push({ worksheetSheetName: sheet.getSheetName(), tableName: table.name, ...options })
    }
    for (const before of source?.tables ?? []) {
      const table = tables.find((item: any) => item.subUnitId === sheet.getSheetId() && item.id === `file-table-${sheet.getSheetId()}-${before.id}`)
      const edit: TableEdit = { worksheetSheetName: sheet.getSheetName(), tableName: before.name }
      if (!table) { edits.push({ ...edit, remove: true }); continue }
      const columnNames = table.columns.map((column: any) => column.displayName)
      const renamed = table.name !== before.displayName
      const resized = (['startRow', 'endRow', 'startColumn', 'endColumn'] as const).some(key => table.range[key] !== before.range[key])
      const columnsChanged = columnNames.length !== before.columns.length || columnNames.some((name: string, index: number) => name !== before.columns[index]?.name)
      const totalsChanged = table.meta?.nativeTotalsRowCount !== undefined && table.meta.nativeTotalsRowCount !== before.totalsRowCount
      const headerChanged = typeof table.showHeader === 'boolean' && table.showHeader !== (before.headerRowCount > 0)
      const filterChanged = typeof table.meta?.nativeFilterButton === 'boolean' && table.meta.nativeFilterButton !== (headerChanged ? table.showHeader : before.filterButton)
      const styleChanged = table.meta && Object.hasOwn(table.meta, 'nativeTableStyleName') && table.meta.nativeTableStyleName !== (before.style?.name ?? '')
      const options: { firstColumn?: boolean; lastColumn?: boolean; bandedRows?: boolean; bandedColumns?: boolean } = {}
      for (const [option, field] of [['showFirstColumn', 'firstColumn'], ['showLastColumn', 'lastColumn'], ['showRowStripes', 'bandedRows'], ['showColumnStripes', 'bandedColumns']] as const) {
        const value = table.meta?.nativeTableStyle?.[option]
        if (typeof value === 'boolean' && value !== (before.style?.[option] ?? false)) options[field] = value
      }
      if (renamed || resized || columnsChanged || totalsChanged || headerChanged || filterChanged || styleChanged || Object.keys(options).length) edits.push({ ...edit,
        ...(renamed ? { name: table.name } : {}),
        ...(resized ? { area: { startRow: table.range.startRow, endRow: table.range.endRow,
          startColumn: table.range.startColumn, endColumn: table.range.endColumn } } : {}),
        ...(columnsChanged ? { columnNames } : {}),
        ...(totalsChanged ? { totalsRow: table.meta.nativeTotalsRowCount > 0 } : {}),
        ...(headerChanged ? { headerRow: table.showHeader } : {}),
        ...(filterChanged ? { filterButton: table.meta.nativeFilterButton } : {}),
        ...(styleChanged ? { style: table.meta.nativeTableStyleName } : {}),
        ...options,
      })
    }
  }
  edits.sort((a, b) => Number(!!b.remove) - Number(!!a.remove))
  return [...(edits.length ? [{ kind: 'applyTableEdits', edits }] : []), ...(additions.length ? [{ kind: 'applyTableAdditions', additions }] : []), ...(newTableEdits.length ? [{ kind: 'applyTableEdits', edits: newTableEdits }] : [])]
}

// 默认使用空主题；来源表的内置样式由工作簿主题资源单独注册。
export const workbookTableConfig: IUniverSheetsTableConfig = {
  userThemes: [{ name: 'native-file-table', style: {} }], defaultThemeIndex: 0,
}

// 文件表格先作为官方资源加载；Table Design 写入链另行接入。
export function withWorkbookTables<T extends { sheets: Record<string, { id: string; name: string }> }>(data: T, model: WorkbookModel): T & { resources: { name: string; data: string }[] } {
  const resource: Record<string, unknown> = {}
  for (const sheet of Object.values(data.sheets)) {
    const source = model.sheets.find(item => item.name === sheet.name)
    if (source?.tablesReadOnlyReason || !source?.tables?.length) continue
    resource[sheet.id] = { tables: source.tables.map(table => ({
      id: `file-table-${sheet.id}-${table.id}`, name: table.displayName, range: table.range,
      options: { showHeader: table.headerRowCount > 0, showFooter: table.totalsRowCount > 0, tableStyleId: '' },
      columns: table.columns.map(column => ({ id: column.id, displayName: column.name, dataType: 'string', formula: '', meta: {}, style: {} })),
      meta: { nativeFilterButton: table.filterButton, nativeTotalsRowCount: table.totalsRowCount, nativeTableStyle: structuredClone(table.style), ...(table.customStyle ? { nativeCustomTableStyle: structuredClone(table.customStyle) } : {}), nativeThemePalette: structuredClone(model.themePalette) },
      filters: { tableColumnFilterList: [] },
    })), tableFilteredOutRows: [] }
  }
  const existing = (data as T & { resources?: { name: string; data: string }[] }).resources ?? []
  return withNativeTableThemes(Object.assign(data, { resources: [...existing.filter(item => item.name !== 'SHEET_TABLE_PLUGIN'),
    ...(Object.keys(resource).length ? [{ name: 'SHEET_TABLE_PLUGIN', data: JSON.stringify(resource) }] : [])] }), model)
}

// 固定源 univer-sync.ts resolveDvListSource：单列表引用按数据区展开计算副本。
export function resolveTableListSource(formula: string, workbook: any): string {
  const match = formula.match(/^=([\p{L}_\\][\p{L}\p{N}_.\\]*)(?:\[([^\[\]]+)\]|\[\[([^\[\]]+)\]\])$/u)
  if (!match) return formula
  const columnName = (match[2] ?? match[3])!
  const tables = (workbook?.getTableList?.() ?? []).filter((table: any) => table.name.toLowerCase() === match[1]!.toLowerCase())
  if (tables.length !== 1) return '=#NAME?'
  const table = tables[0], column = table.columns.findIndex((item: any) => item.displayName.toLowerCase() === columnName.toLowerCase())
  const first = table.range.startRow + (table.showHeader ? 1 : 0)
  const last = table.range.endRow - (table.meta?.nativeTotalsRowCount ?? 0)
  const sheet = workbook.getSheetBySheetId(table.subUnitId)
  if (column < 0 || first > last || !sheet) return '=#NAME?'
  const letter = columnLabel(table.range.startColumn + column)
  return `='${sheet.getSheetName().replaceAll("'", "''")}'!$${letter}$${first + 1}:$${letter}$${last + 1}`
}

// 与保存复用同一表格结构校验，在基础 mutation 前拒绝不可落盘的删除。
export function preflightTableStructure(workbook: any, command: any) {
  const insertions = new Map<string, { range: ReturnType<typeof parseRange>; insertions: ReturnType<typeof shiftTablePart>['insertions'] }>()
  const ids: Record<string, string> = {
    'sheet.command.insert-row': 'sheet.mutation.insert-row', 'sheet.command.remove-row': 'sheet.mutation.remove-rows',
    'sheet.command.insert-col': 'sheet.mutation.insert-col', 'sheet.command.remove-col': 'sheet.mutation.remove-col',
  }
  const params = command.params
  if (!ids[command.id] || !params?.range) return insertions
  const sheetId = params.subUnitId ?? workbook?.getActiveSheet()?.getSheetId()
  const mutation = structuralMutation(ids[command.id]!, { ...params, subUnitId: sheetId })
  if (!mutation) return insertions
  for (const table of workbook?.getTableList?.() ?? []) {
    if (table.subUnitId !== sheetId) continue
    const range = table.range
    const ref = `${formatAddress(range.startRow, range.startColumn)}:${formatAddress(range.endRow, range.endColumn)}`
    const columns = table.columns.map((column: any) => `<tableColumn id="${escapeXmlAttribute(String(column.id))}" name="${escapeXmlAttribute(column.displayName)}"/>`).join('')
    const shifted = shiftTablePart(`<table name="${escapeXmlAttribute(table.name)}" ref="${ref}" headerRowCount="${table.showHeader ? 1 : 0}" totalsRowCount="${table.meta?.nativeTotalsRowCount ?? 0}"><tableColumns count="${table.columns.length}">${columns}</tableColumns></table>`, [shiftSpecOf(mutation.op)])
    insertions.set(table.id, { range: parseRange(shifted.xml.match(/\bref="([^"]+)"/)![1]!), insertions: shifted.insertions })
  }
  return insertions
}
