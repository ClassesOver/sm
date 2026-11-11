import { ICommandService, CellValueType } from '@univerjs/core'
import { columnLabel, parseRange } from '@sheets-web/xlsx-engine'
import { WORKBOOK_MAX_CELL_EDITS } from './workbook-edit-budget'

export type ConsolidateFunction = 'sum' | 'count' | 'average' | 'max' | 'min'
export interface ConsolidateInput { fn: ConsolidateFunction; references: readonly string[]; leftLabels: boolean }
export interface ConsolidateWriteParams {
  unitId: string
  subUnitId: string
  value: Record<number, Record<number, { v: string | null; f: string | null; p: null; t?: CellValueType }>>
}
const FUNCTIONS = { sum: 'SUM', count: 'COUNTA', average: 'AVERAGE', max: 'MAX', min: 'MIN' }
const REFERENCE = /^(?:('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?(\$?[A-Za-z]{1,3}\$?[0-9]+(?::\$?[A-Za-z]{1,3}\$?[0-9]+)?)$/
export function parseConsolidateReference(text: string) {
  const match = REFERENCE.exec(text.trim())
  if (!match) return null
  try {
    const range = parseRange(match[2]!.toUpperCase().replaceAll('$', ''))
    if (range.endRow > 1048575 || range.endColumn > 16383) return null
    const qualifier = match[1]
    return { sheetName: qualifier === undefined ? null : qualifier.startsWith("'") ? qualifier.slice(1, -1).replaceAll("''", "'") : qualifier, range }
  } catch { return null }
}
const prefix = (name: string) => /^[A-Za-z_][A-Za-z0-9_.]*$/.test(name) ? `${name}!` : `'${name.replaceAll("'", "''")}'!`

// 固定源 consolidate.ts：按位置或左列标签生成实时引用公式；整块一次官方写入。
export function applyConsolidate(runtime: any, input: ConsolidateInput, protectedSheet: (id: string) => boolean = () => false, beforeWrite?: (params: ConsolidateWriteParams) => void): { rows: number; columns: number; sources: number } {
  const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet(), active = workbook?.getActiveRange()
  if (!sheet || !active) throw new Error('请先选择合并计算的目标单元格')
  if (protectedSheet(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
  if (!Object.hasOwn(FUNCTIONS, input.fn) || !input.references.length) throw new Error('请选择汇总函数并添加至少一个来源引用')
  if (input.leftLabels && (input.fn === 'max' || input.fn === 'min')) throw new Error('左列标签模式不支持最大值或最小值')
  const areas = input.references.map(reference => {
    const parsed = parseConsolidateReference(reference)
    if (!parsed) throw new Error(`来源引用无效或超出工作表边界：${reference}`)
    const name = parsed.sheetName ?? sheet.getSheetName()
    const source = workbook.getSheets().find((candidate: any) => candidate.getSheetName().toLowerCase() === name.toLowerCase())
    if (!source) throw new Error(`找不到来源工作表：${name}`)
    const { startRow, startColumn, endRow, endColumn } = parsed.range
    return { source, name: source.getSheetName() as string, startRow, startColumn, rows: endRow - startRow + 1, columns: endColumn - startColumn + 1 }
  })
  const row = active.getRow(), column = active.getColumn()
  const checkExtent = (rows: number, columns: number) => {
    if (row + rows > 1048576 || column + columns > 16384) throw new Error('合并计算目标超出工作表边界')
    if (rows * columns > WORKBOOK_MAX_CELL_EDITS) throw new Error('合并计算超出单元格操作预算，请缩小来源范围')
  }
  let labels: string[] = [], labelSets: Set<string>[] = []
  const columns = Math.max(...areas.map(area => area.columns))
  if (input.leftLabels) {
    if (areas.some(area => area.columns < 2)) throw new Error('左列标签模式的每个来源至少需要两列')
    const seen = new Set<string>()
    labelSets = areas.map(area => {
      area.source.getRange(area.startRow, area.startColumn, area.rows, 1)
      const own = new Set<string>(), core = area.source.getSheet()
      // 与原生 getValues() 同样读取 getCell().v，避免整列生成百万个空行数组。
      for (let offset = 0; offset < area.rows; offset++) {
        const label = String(core.getCell(area.startRow + offset, area.startColumn)?.v ?? '')
        if (label === '') continue
        own.add(label)
        if (!seen.has(label)) { seen.add(label); labels.push(label); checkExtent(labels.length, columns) }
      }
      return own
    })
    if (!labels.length) throw new Error('来源左列没有可合并的标签')
  }
  const rows = input.leftLabels ? labels.length : Math.max(...areas.map(area => area.rows))
  checkExtent(rows, columns)
  sheet.getRange(row, column, rows, columns)
  if (areas.some(area => area.name === sheet.getSheetName() && row < area.startRow + area.rows && area.startRow < row + rows && column < area.startColumn + area.columns && area.startColumn < column + columns)) throw new Error('合并计算目标不能与来源区域重叠')
  const value: ConsolidateWriteParams['value'] = {}
  for (let r = 0; r < rows; r++) {
    const line: ConsolidateWriteParams['value'][number] = {}
    for (let c = 0; c < columns; c++) {
      if (input.leftLabels && c === 0) { line[column + c] = { v: labels[r], t: CellValueType.STRING, f: null, p: null }; continue }
      let formula: string | undefined
      if (!input.leftLabels) {
        const refs = areas.filter(area => r < area.rows && c < area.columns).map(area => `${prefix(area.name)}${columnLabel(area.startColumn + c)}${area.startRow + r + 1}`)
        if (refs.length) formula = `${FUNCTIONS[input.fn]}(${refs.join(',')})`
      } else {
        const criteria = `$${columnLabel(column)}${row + r + 1}`
        const parts = areas.flatMap((area, index) => {
          if (!labelSets[index]!.has(labels[r]!) || c >= area.columns) return []
          const labelColumn = columnLabel(area.startColumn), valueColumn = columnLabel(area.startColumn + c), sheetPrefix = prefix(area.name)
          const labelRange = `${sheetPrefix}$${labelColumn}$${area.startRow + 1}:$${labelColumn}$${area.startRow + area.rows}`
          const valueRange = `${sheetPrefix}${valueColumn}${area.startRow + 1}:${valueColumn}${area.startRow + area.rows}`
          return [{ sum: `SUMIF(${labelRange},${criteria},${valueRange})`, count: `COUNTIF(${labelRange},${criteria})` }]
        })
        if (parts.length) {
          const sum = parts.map(part => part.sum).join('+'), count = parts.map(part => part.count).join('+')
          formula = input.fn === 'sum' ? sum : input.fn === 'count' ? count : `(${sum})/(${count})`
        }
      }
      line[column + c] = { v: null, f: formula === undefined ? null : `=${formula}`, p: null }
    }
    value[row + r] = line
  }
  const params: ConsolidateWriteParams = { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), value }
  beforeWrite?.(params)
  if (!runtime.univer.__getInjector().get(ICommandService).syncExecuteCommand('sheet.command.set-range-values', params)) throw new Error('合并计算写入未执行')
  return { rows, columns, sources: areas.length }
}
