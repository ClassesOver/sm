import type { TableModel } from '@genoffice/docx-engine'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { NativeOperation } from './native-draft'

export interface DocxNestedCellAnchor { cellId: string; expectedObjectSha256: string; editable: boolean; paragraphs: string[]; readOnlyReason?: string }
export interface DocxNestedTableAnchor { tableId: string; expectedObjectSha256: string; row: number; column: number; nestedOrdinal: number; cells: DocxNestedCellAnchor[][] }
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
/** 与 bridge 提交文本契约一致；段间换行用数组边界表达。 */
export const isDocxNestedParagraphs = (value: unknown): value is string[] => Array.isArray(value) && value.length > 0 && value.length <= 1000
  && value.every(item => typeof item === 'string' && item.length <= 20000 && !/[\x00-\x1f\u007f\ufffe\uffff]/.test(item))
  && value.reduce((length, item: string) => length + item.length, 0) <= 20000
const identity = (value: unknown): value is string => typeof value === 'string' && value.length > 0
function nestedNode(root: DocxPmNode, anchor: DocxNestedTableAnchor): DocxPmNode {
  const node = root.content?.[anchor.row]?.content?.[anchor.column]?.content?.filter(child => child.type === 'docNestedTable')[anchor.nestedOrdinal]
  if (!node || !node.attrs?.model) throw new Error('嵌套表来源模型定位失效')
  return node
}
function modelOf(node: DocxPmNode): TableModel {
  const model = node.attrs?.model as TableModel | undefined
  if (!model || !Array.isArray(model.rows) || model.rows.some(row => !Array.isArray(row))) throw new Error('嵌套表来源模型无效')
  return model
}
/** 仅对不可变 baseline 调用；返回已核验的 PM 原子节点与签发清单，供输入能力映射使用。 */
export function getDocxNestedTableTargets(root: DocxPmNode, anchor: DocxAnchor): { anchor: DocxNestedTableAnchor; node: DocxPmNode }[] {
  const tableIds = new Set<string>(), cellIds = new Set<string>(), paths = new Set<string>()
  return (anchor.nestedTables ?? []).map(table => {
    const path = JSON.stringify([table.row, table.column, table.nestedOrdinal])
    if (root.type !== 'docTable' || root.attrs?.docxIndex !== anchor.docxIndex || !identity(table.tableId) || !identity(table.expectedObjectSha256)
      || [table.row, table.column, table.nestedOrdinal].some(value => !Number.isSafeInteger(value) || value < 0) || tableIds.has(table.tableId) || paths.has(path)) throw new Error('嵌套表来源身份无效或重复')
    tableIds.add(table.tableId); paths.add(path)
    const node = nestedNode(root, table), model = modelOf(node)
    if (!Array.isArray(table.cells) || table.cells.length !== model.rows.length) throw new Error('嵌套表来源行数失效')
    table.cells.forEach((row, r) => {
      if (!Array.isArray(row) || row.length !== model.rows[r]!.length) throw new Error('嵌套表来源列数失效')
      row.forEach((cell, c) => {
        const source = model.rows[r]![c]!
        if (!cell || !identity(cell.cellId) || typeof cell.expectedObjectSha256 !== 'string' || typeof cell.editable !== 'boolean' || cellIds.has(cell.cellId)
          || !Array.isArray(cell.paragraphs) || !cell.paragraphs.every(item => typeof item === 'string') || !same(source.paras, cell.paragraphs)
          || cell.editable && (!identity(cell.expectedObjectSha256) || !isDocxNestedParagraphs(cell.paragraphs) || !!source.nestedTables?.length)) throw new Error('嵌套单元格来源身份或段落失效')
        cellIds.add(cell.cellId)
      })
    })
    return { anchor: table, node }
  })
}
export function assertDocxNestedOperationBatch(operations: NativeOperation[]): void {
  const targets = new Set<string>()
  for (const op of operations) if (op.kind === 'replaceNestedCellText') {
    const target = JSON.stringify([op.blockId, op.tableId, op.cellId])
    if (targets.has(target)) throw new Error('嵌套单元格草稿目标重复')
    targets.add(target)
    if (operations.some(other => other.blockId === op.blockId && other.kind !== 'replaceNestedCellText')) throw new Error('嵌套改字不能与同根其他操作混合')
  }
}
/** 还原目标 model 后完整核验根表，任何未签发变化和祖先变化均不能混入。 */
export function normalizeDocxNestedTables(original: DocxPmNode, current: DocxPmNode, anchors: DocxAnchor[]): { current: DocxPmNode; operations: NativeOperation[] } {
  const normalized = structuredClone(current), operations: NativeOperation[] = []
  for (const anchor of anchors) {
    const root = original.content?.find(node => node.attrs?.docxIndex === anchor.docxIndex)
    if (!root || !anchor.nestedTables?.length) continue
    const targets = getDocxNestedTableTargets(root, anchor)
    const changedRoot = normalized.content?.find(node => node.attrs?.docxIndex === anchor.docxIndex)
    if (!changedRoot) continue
    const start = operations.length
    for (const { anchor: table, node } of targets) {
      const before = modelOf(node), changedNode = nestedNode(changedRoot, table), after = modelOf(changedNode)
      for (let r = 0; r < table.cells.length; r++) for (let c = 0; c < table.cells[r]!.length; c++) {
        const cell = table.cells[r]![c]!, source = before.rows[r]![c]!, changed = after.rows[r]?.[c]
        if (!changed || same(source, changed)) continue
        if (!cell.editable || !isDocxNestedParagraphs(changed.paras) || same(source.paras, changed.paras)) throw new Error('嵌套单元格只允许已签发的简单文字变化')
        const expected = { ...source, paras: [...changed.paras] }; delete expected.richParas
        if (!same(changed, expected)) throw new Error('嵌套改字不能改变单元格格式或结构')
        operations.push({ kind: 'replaceNestedCellText', blockId: anchor.blockId, tableId: table.tableId, cellId: cell.cellId, expectedObjectSha256: cell.expectedObjectSha256, paragraphs: [...changed.paras] })
        after.rows[r]![c] = structuredClone(source)
      }
    }
    if (operations.length > start && !same(root, changedRoot)) throw new Error('嵌套改字不能与祖先或同根其他变化混合')
  }
  return { current: normalized, operations }
}
/** 从原始来源定位全部目标后，再对副本应用；同一来源身份不能使用旧草稿。 */
export function replayDocxNestedTables(original: DocxPmNode, result: DocxPmNode, operations: NativeOperation[], anchors: DocxAnchor[]): void {
  assertDocxNestedOperationBatch(operations)
  for (const op of operations) if (op.kind === 'replaceNestedCellText') {
    if (Object.keys(op).some(key => !['kind', 'blockId', 'tableId', 'cellId', 'expectedObjectSha256', 'paragraphs'].includes(key)) || !isDocxNestedParagraphs(op.paragraphs)) throw new Error('嵌套单元格草稿字段无效')
    const anchor = anchors.find(item => item.blockId === op.blockId), root = anchor && original.content?.find(node => node.attrs?.docxIndex === anchor.docxIndex)
    if (!anchor || !root) throw new Error('嵌套表草稿不属于当前来源')
    const target = getDocxNestedTableTargets(root, anchor).find(item => item.anchor.tableId === op.tableId)
    if (!target) throw new Error('嵌套表草稿身份失效')
    let coordinate: [number, number] | undefined
    target.anchor.cells.forEach((row, r) => row.forEach((cell, c) => {
      if (cell.cellId === op.cellId && cell.editable && cell.expectedObjectSha256 === op.expectedObjectSha256) coordinate = [r, c]
    }))
    if (!coordinate) throw new Error('嵌套单元格草稿身份或能力失效')
    const resultRoot = result.content!.find(node => node.attrs?.docxIndex === anchor.docxIndex)!
    const cell = modelOf(nestedNode(resultRoot, target.anchor)).rows[coordinate[0]]![coordinate[1]]!
    cell.paras = [...op.paragraphs]; delete cell.richParas
  }
}
