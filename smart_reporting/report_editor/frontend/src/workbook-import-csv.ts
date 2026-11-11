import { CellValueType } from '@univerjs/core'
import type { FWorkbook } from '@univerjs/sheets/facade'
import { columnLabel } from '@sheets-web/xlsx-engine'
import { decodeCsvBuffer, isNumericCell, parseCsv } from './workbook-vendor/grid/csv-import'

export interface WorkbookCsvImportResult { rows: number; columns: number; address: string }
export interface WorkbookCsvImportOptions {
  getWorkbook: () => FWorkbook | null | undefined
  setMessage: (message: string) => void
  onImported?: (result: WorkbookCsvImportResult) => void
  isBlocked?: () => boolean
}

// 与源端相同：选区左上角、一次 setValues，保留单元格格式和原生撤销重做。
export function importCsvIntoSelection(workbook: FWorkbook, text: string): WorkbookCsvImportResult {
  const sheet = workbook.getActiveSheet(), range = workbook.getActiveRange()
  if (!sheet || !range) throw new Error('请先选择导入起始单元格')
  const rows = parseCsv(text), columns = rows.reduce((width, row) => Math.max(width, row.length), 0)
  if (!rows.length || !columns) throw new Error('CSV 文件没有可导入的数据')
  if (rows.length * columns > 50_000) throw new Error('CSV 导入不能超过 50000 个单元格，请将大文件单独打开')
  const row = range.getRow(), column = range.getColumn()
  if (row + rows.length > sheet.getMaxRows() || column + columns > sheet.getMaxColumns()) throw new Error('CSV 数据超出当前工作表范围，请先增加行列')
  const values = rows.map(fields => Array.from({ length: columns }, (_, index) => {
    const value = fields[index] ?? ''
    // 明确 STRING，防止 '=...'、'@...' 等外部文本被当成公式执行。
    return isNumericCell(value) ? { v: Number(value), t: CellValueType.NUMBER, f: null, si: null } : { v: value, t: CellValueType.STRING, f: null, si: null }
  }))
  const target = sheet.getRange(row, column, rows.length, columns)
  target.setValues(values)
  // FRange.setValues 会吞掉原生命令的 false 返回；读回确认拒绝时不报成功。
  const actual = target.getCellDatas()
  if (values.some((fields, r) => fields.some((expected, c) => {
    const cell = actual[r]?.[c]
    return cell?.v !== expected.v || cell?.t !== expected.t || Boolean(cell?.f) || Boolean(cell?.si)
  }))) throw new Error('CSV 导入未应用：原生命令被拒绝，或目标单元格未完整写入')
  return { rows: rows.length, columns, address: `${columnLabel(column)}${row + 1}` }
}

export function openWorkbookCsvImport(options: WorkbookCsvImportOptions): () => void {
  let disposed = false, reading = false
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain'
  input.hidden = true
  const dispose = () => { disposed = true; input.remove(); input.onchange = null; input.oncancel = null }
  const fail = (error: unknown) => { if (!disposed) options.setMessage(error instanceof Error ? error.message : 'CSV 导入失败'); dispose() }
  const workbook = options.getWorkbook(), sheet = workbook?.getActiveSheet(), selection = workbook?.getActiveRange()
  if (!workbook || !sheet || !selection) { fail(new Error('请先选择导入起始单元格')); return dispose }
  if (options.isBlocked?.()) { fail(new Error('当前工作簿已锁定，不能导入 CSV')); return dispose }
  const workbookCore = workbook.getWorkbook(), sheetCore = sheet.getSheet(), selected = JSON.stringify(selection.getRange()), snapshot = JSON.stringify(workbook.save())
  const validate = () => {
    if (options.isBlocked?.()) throw new Error('当前工作簿已锁定，不能导入 CSV')
    const current = options.getWorkbook()
    if (current?.getWorkbook() !== workbookCore || current.getActiveSheet()?.getSheet() !== sheetCore || JSON.stringify(current.getActiveRange()?.getRange()) !== selected || JSON.stringify(current.save()) !== snapshot) throw new Error('工作簿、工作表或选区已变化，请重新导入 CSV')
  }
  input.oncancel = dispose
  input.onchange = () => {
    if (reading || disposed) return
    const file = input.files?.[0]
    if (!file) { dispose(); return }
    if (file.size > 32 * 1024 * 1024) { fail(new Error('CSV 文件不能超过 32 MiB')); return }
    reading = true
    void (async () => {
      validate()
      const bytes = new Uint8Array(await file.arrayBuffer())
      if (disposed) return
      validate()
      if ((bytes[0] === 255 && bytes[1] === 254 || bytes[0] === 254 && bytes[1] === 255) && bytes.length % 2) throw new Error('CSV 的 UTF-16 编码不完整')
      const text = decodeCsvBuffer(bytes, 'gb18030')
      if (text.includes('�') || text.includes('\0')) throw new Error('CSV 文件编码无法识别，请使用 UTF-8 编码重试')
      const result = importCsvIntoSelection(workbook, text)
      options.onImported?.(result)
      options.setMessage(`已将 ${result.rows} 行 × ${result.columns} 列导入到 ${result.address}`)
      dispose()
    })().catch(fail)
  }
  document.body.append(input)
  input.click()
  return dispose
}
