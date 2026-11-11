import type { UniverRuntime } from './workbook-vendor/grid/create-univer'
import type { NativeOfficeReadContext } from './native-api'
import type { NativeOperation } from './native-draft'

/** 在异步草稿采集前后核验真实网格选区，禁止读取尚未确认的单元格输入。 */
export async function captureWorkbookReadContext(scope: 'document' | 'selection', options: {
  runtime: UniverRuntime
  closed: () => boolean
  epoch: () => number
  persisted: () => Promise<unknown>
  operations: () => Promise<NativeOperation[]>
  setOperations: (operations: NativeOperation[]) => void
}): Promise<NativeOfficeReadContext> {
  if (options.closed()) throw new Error('当前文档已关闭或正在保存')
  const workbook = () => options.runtime.univerAPI.getActiveWorkbook()
  const captureSelection = () => {
    if (scope === 'document') return null
    const sheet = workbook()?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
    if (!sheet || !range) throw new Error('选区无法可靠对应来源，请选择有效单元格区域')
    return { sheetName: sheet.getSheetName(), startRow: range.getRow(), endRow: range.getRow()+range.getHeight()-1, startColumn: range.getColumn(), endColumn: range.getColumn()+range.getWidth()-1 }
  }
  if (workbook()?.isCellEditing?.()) throw new Error('请先按 Enter 确认正在编辑的单元格，再开始阅读')
  const selection = captureSelection(), epoch = options.epoch()
  await options.persisted()
  const operations = await options.operations()
  if (options.closed() || epoch !== options.epoch() || workbook()?.isCellEditing?.() || JSON.stringify(selection) !== JSON.stringify(captureSelection())) throw new Error('草稿或选区已变化，请重新阅读')
  options.setOperations(operations)
  return { operations: structuredClone(operations), selection }
}
