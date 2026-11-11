import { generateRandomId, ICommandService, IUndoRedoService } from '@univerjs/core'
import { parseAddress, parseRange, type CellCoordinates, type RangeBounds } from '@sheets-web/xlsx-engine'
import type { CalculationControl } from './workbook-calculation'

export const MAX_DATA_TABLE_CELLS = 10000
export type DataTableKind = 'column' | 'row' | 'grid'
export type DataTablePlanError = 'noInputCell' | 'sameInputCell' | 'badShape' | 'inputInsideTable' | 'tooManyCells'
export interface DataTableInput {
  tableRange: string
  rowInputCell: string | null
  columnInputCell: string | null
  onProgress?: (done: number, total: number) => void
}
export interface DataTablePlan {
  kind: DataTableKind
  formulaCell: CellCoordinates
  rowValueCells: CellCoordinates[]
  columnValueCells: CellCoordinates[]
  resultStart: CellCoordinates
  resultRows: number
  resultColumns: number
}
export function planDataTable(bounds: RangeBounds, rowInput: CellCoordinates | null, columnInput: CellCoordinates | null): DataTablePlan | DataTablePlanError {
  if (!rowInput && !columnInput) return 'noInputCell'
  if (rowInput && columnInput && rowInput.row === columnInput.row && rowInput.column === columnInput.column) return 'sameInputCell'
  for (const cell of [rowInput, columnInput]) if (cell && cell.row >= bounds.startRow && cell.row <= bounds.endRow && cell.column >= bounds.startColumn && cell.column <= bounds.endColumn) return 'inputInsideTable'
  const rows = bounds.endRow - bounds.startRow + 1, columns = bounds.endColumn - bounds.startColumn + 1
  if (rows < 2 || columns < 2 || !rowInput && columns !== 2 || !columnInput && rows !== 2) return 'badShape'
  const kind = rowInput && columnInput ? 'grid' : rowInput ? 'row' : 'column'
  const resultRows = kind === 'row' ? 1 : rows - 1, resultColumns = kind === 'column' ? 1 : columns - 1
  if (resultRows * resultColumns > MAX_DATA_TABLE_CELLS) return 'tooManyCells'
  return { kind, resultRows, resultColumns,
    formulaCell: { row: kind === 'row' ? bounds.endRow : bounds.startRow, column: kind === 'column' ? bounds.endColumn : bounds.startColumn },
    resultStart: { row: kind === 'row' ? bounds.endRow : bounds.startRow + 1, column: kind === 'column' ? bounds.endColumn : bounds.startColumn + 1 },
    rowValueCells: rowInput ? Array.from({ length: columns - 1 }, (_, index) => ({ row: bounds.startRow, column: bounds.startColumn + index + 1 })) : [],
    columnValueCells: columnInput ? Array.from({ length: rows - 1 }, (_, index) => ({ row: bounds.startRow + index + 1, column: bounds.startColumn })) : [],
  }
}
const messages: Record<DataTablePlanError, string> = {
  noInputCell: '请至少指定一个输入单元格', sameInputCell: '行和列输入单元格不能相同', badShape: '数据表区域形状不匹配',
  inputInsideTable: '输入单元格不能位于数据表区域内', tooManyCells: '数据表结果不能超过10000个单元格',
}
type Scalar = number | string | boolean | null

// 固定源 data-table.ts：逐值代入原生公式引擎，写入静态结果；不创建 TABLE 公式。
export function installDataTable(runtime: any, calculation: CalculationControl, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  let disposed = false, running = false, cancel: (() => void) | undefined
  return {
    isRunning: () => running,
    dispose() { disposed = true; cancel?.() },
    async apply(input: DataTableInput): Promise<{ kind: DataTableKind; cells: number }> {
      if (disposed) throw new Error('数据表计算已关闭')
      if (running) throw new Error('数据表正在计算，请稍候')
      const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
      if (!sheet) throw new Error('当前没有可编辑工作表')
      const unitId = workbook.getId(), subUnitId = sheet.getSheetId(), core = workbook.getWorkbook(), sheetCore = sheet.getSheet()
      const valid = () => runtime.univerAPI.getActiveWorkbook()?.getWorkbook() === core && workbook.getSheetBySheetId(subUnitId)?.getSheet() === sheetCore
      const check = () => { if (disposed || !valid()) throw new Error('数据表来源工作簿已变化，请重新打开对话框') }
      if (protectedSheet(subUnitId)) throw new Error('工作表受保护，请先撤销保护')
      const address = (value: string) => {
        const cell = parseAddress(value.trim().toUpperCase())
        if (cell.row > 1048575 || cell.column > 16383) throw new Error('单元格超出工作表边界')
        return cell
      }
      let bounds: RangeBounds, rowInput: CellCoordinates | null, columnInput: CellCoordinates | null
      try {
        bounds = parseRange(input.tableRange.trim().toUpperCase()); address(input.tableRange.split(':')[0]!); address(input.tableRange.split(':').at(-1)!)
        rowInput = input.rowInputCell ? address(input.rowInputCell) : null; columnInput = input.columnInputCell ? address(input.columnInputCell) : null
      } catch { throw new Error('数据表区域或输入单元格无效') }
      const plan = planDataTable(bounds, rowInput, columnInput)
      if (typeof plan === 'string') throw new Error(messages[plan])
      const range = (cell: CellCoordinates) => sheet.getRange(cell.row, cell.column, 1, 1)
      const formula = range(plan.formulaCell)
      if (!formula.getFormula()) throw new Error('数据表的结果来源必须是公式单元格')
      const inputs = [rowInput, columnInput].filter((cell): cell is CellCoordinates => !!cell).map(cell => ({ cell, range: range(cell) }))
      const originals = inputs.map(({ range }) => {
        const value = range.getValue()
        if (range.getFormula() || value !== null && value !== undefined && typeof value !== 'number') throw new Error('输入单元格必须为空或数值，不能含公式')
        return value ?? null
      })
      const readNumbers = (cells: CellCoordinates[]) => cells.map(cell => {
        const value = range(cell).getValue()
        if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('代入值必须为数值')
        return value
      })
      const rowValues = readNumbers(plan.rowValueCells), columnValues = readNumbers(plan.columnValueCells)
      const id = generateRandomId(), item = { unitID: unitId, id, undoMutations: [] as any[], redoMutations: [] as any[] }
      const write = (area: RangeBounds, value: unknown) => {
        const before = item.undoMutations.length
        if (!commands.syncExecuteCommand('sheet.command.set-range-values', { unitId, subUnitId, range: area, value })) throw new Error('数据表写入未执行')
        // 0.25.1 batching按正序追加undo；多次改同一输入必须按命令组逆序撤销。
        const added = item.undoMutations.splice(before)
        item.undoMutations.unshift(...added)
      }
      const writeInput = (index: number, value: number | null) => {
        const cell = inputs[index]!.cell
        write({ startRow: cell.row, endRow: cell.row, startColumn: cell.column, endColumn: cell.column }, { v: value, f: null, p: null })
      }
      const recalc = (mutate: () => void) => new Promise<void>((resolve, reject) => {
        const finish = (error?: Error) => { subscription.dispose(); clearTimeout(timer); cancel = undefined; error ? reject(error) : resolve() }
        const subscription = runtime.univerAPI.getFormula().calculationEnd(() => finish())
        // 与固定源一致：等值写入可能不产生新计算事件，2秒后结束等待。
        const timer = setTimeout(() => finish(), 2000)
        cancel = () => finish(new Error('数据表计算已取消'))
        try { check(); mutate(); if (calculation.manual()) calculation.calculateNow() } catch (error) { finish(error as Error) }
      })
      const batch = history.__tempBatchingUndoRedo(unitId)
      running = true
      history.pushUndoRedo(item)
      try {
        const results: Scalar[][] = [], total = plan.resultRows * plan.resultColumns
        let done = 0
        const evaluate = async (index: number, value: number) => { check(); await recalc(() => writeInput(index, value)); check() }
        const read = (): Scalar => {
          const value = formula.getValue()
          input.onProgress?.(++done, total)
          return typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean' ? value : null
        }
        if (plan.kind === 'grid') {
          for (const column of columnValues) {
            await evaluate(1, column)
            const row: Scalar[] = []
            for (const value of rowValues) { await evaluate(0, value); row.push(read()) }
            results.push(row)
          }
        } else {
          const values: Scalar[] = []
          for (const value of plan.kind === 'column' ? columnValues : rowValues) { await evaluate(0, value); values.push(read()) }
          results.push(...(plan.kind === 'column' ? values.map(value => [value]) : [values]))
        }
        for (let index = 0; index < inputs.length; index++) await recalc(() => writeInput(index, originals[index]))
        check()
        const matrix: Record<number, Record<number, { v: Scalar; f: null; p: null }>> = {}
        results.forEach((row, r) => row.forEach((value, c) => { (matrix[plan.resultStart.row + r] ??= {})[plan.resultStart.column + c] = { v: value, f: null, p: null } }))
        write({ startRow: plan.resultStart.row, endRow: plan.resultStart.row + plan.resultRows - 1,
          startColumn: plan.resultStart.column, endColumn: plan.resultStart.column + plan.resultColumns - 1 }, matrix)
        return { kind: plan.kind, cells: total }
      } catch (error) {
        // 官方rollback只移除本批唯一id；不能把恢复动作写到同id重建后的core。
        if (valid()) history.rollback(id, unitId)
        throw error
      } finally { batch.dispose(); cancel = undefined; running = false }
    },
  }
}
