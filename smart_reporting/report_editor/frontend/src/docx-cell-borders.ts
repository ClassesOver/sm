import { Extension, type Editor } from '@tiptap/core'
import { NodeSelection, type EditorState } from '@tiptap/pm/state'
import { closeHistory } from '@tiptap/pm/history'
import { CellSelection, isInTable, selectedRect, TableMap } from '@tiptap/pm/tables'
import { DOCX_CELL_BORDER_SIDES, docxCellBorderRect, docxCellBorderSideLine, safeDocxCellBorderSteps, type DocxCellBorderMode, type DocxCellBorderStep } from '../../../reporting/doc_engine/bridge/docx-cell-borders-spec'
import type { DocxPmNode } from './docx-operations'
export interface DocxCellBordersAnchor { docxIndex: number; blockId: string; expectedObjectSha256: string; bordersEditable?: boolean; bordersReadOnlyReason?: string; cells?: { cellId: string }[][] }
export interface DocxCellBordersOperation { [key: string]: unknown; kind: 'setTableCellBorders'; blockId: string; expectedObjectSha256: string; steps: DocxCellBorderStep[] }
export const NativeCellBorders = Extension.create({ name: 'nativeCellBorders', addGlobalAttributes: () => [{ types: ['docTable'], attributes: { nativeCellBorders: { default: null, rendered: false } } }] })
function fail(): never { throw new Error('单元格边框来源或草稿无效；合并、嵌套、修订及同表混合编辑暂不支持') }
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
function project(source: DocxPmNode, steps: DocxCellBorderStep[], anchor: DocxCellBordersAnchor): DocxPmNode {
  if (!anchor.bordersEditable || !anchor.cells || source.type !== 'docTable' || source.content?.length !== anchor.cells.length || source.content.some((row, r) => row.content?.length !== anchor.cells![r]?.length)) fail()
  const table = structuredClone(source)
  for (const step of steps) {
    const rect = docxCellBorderRect(step, anchor.cells)
    for (let r = rect.top; r < rect.bottom; r++) for (let c = rect.left; c < rect.right; c++) {
      const cell = table.content![r]!.content![c]!, borders = { ...((cell.attrs?.borders as Record<string, unknown> | null) ?? {}) }
      let changed = false
      for (const side of DOCX_CELL_BORDER_SIDES) {
        const value = docxCellBorderSideLine(step.mode, side, { top: r === rect.top, bottom: r === rect.bottom - 1, left: c === rect.left, right: c === rect.right - 1 }, step.pen)
        if (value) { borders[side] = value; changed = true }
      }
      if (changed) cell.attrs = { ...cell.attrs, borders }
    }
    const borders = table.attrs?.borders as Record<string, unknown> | null | undefined
    if (step.mode === 'none' && borders && (borders.insideH || borders.insideV)) {
      const { insideH: _h, insideV: _v, ...rest } = borders
      table.attrs = { ...table.attrs, borders: Object.keys(rest).length ? rest : null }
    }
  }
  table.attrs = { ...table.attrs, nativeCellBorders: steps }
  return table
}
function target(state: EditorState) {
  if (state.selection instanceof NodeSelection && state.selection.node.type.name === 'docTable') {
    const map = TableMap.get(state.selection.node), start = state.selection.from + 1
    state = state.apply(state.tr.setSelection(CellSelection.create(state.doc, start + map.map[0]!, start + map.map[map.map.length - 1]!)))
  }
  if (!isInTable(state)) return null
  const rect = selectedRect(state)
  return { state, rect, pos: rect.tableStart - 1, table: rect.table }
}
export function docxCellBordersUnavailable(editor: Editor, anchors: readonly DocxCellBordersAnchor[]): string | null {
  if (!editor.isEditable) return '当前文档只读'
  const current = target(editor.state)
  if (!current) return '请先选择表格中的单元格'
  const anchor = anchors.find(anchor => anchor.docxIndex === current.table.attrs.docxIndex)
  if (!anchor?.bordersEditable) return anchor?.bordersReadOnlyReason ?? '当前来源表格暂不能修改单元格边框'
  if (current.table.attrs.nativeTableStructure || current.table.attrs.nativeTableInsert) return '请先保存表格结构修改，再调整单元格边框'
  if (current.table.attrs.nativeTableStyle) return '表格样式修改后不能与同表其他修改混用，请先保存'
  return null
}
export function applyDocxCellBorders(editor: Editor, mode: DocxCellBorderMode, pen: unknown, anchors: readonly DocxCellBordersAnchor[]): boolean {
  if (!editor.isEditable) return false
  const reason = docxCellBordersUnavailable(editor, anchors)
  if (reason) throw new Error(reason)
  editor.view.focus()
  const current = target(editor.state)!, anchor = anchors.find(anchor => anchor.docxIndex === current.table.attrs.docxIndex)!
  const explicit = current.state.selection instanceof CellSelection
  const range = explicit ? { fromCellId: anchor.cells?.[current.rect.top]?.[current.rect.left]?.cellId, toCellId: anchor.cells?.[current.rect.bottom - 1]?.[current.rect.right - 1]?.cellId } : null
  const step = safeDocxCellBorderSteps([{ range, mode, pen }])[0]!, old = current.table.attrs.nativeCellBorders
  const steps = safeDocxCellBorderSteps([...(old == null ? [] : safeDocxCellBorderSteps(old)), step])
  const next = project(current.table.toJSON() as DocxPmNode, [step], anchor)
  next.attrs!.nativeCellBorders = steps
  const beforeAttrs = { ...current.table.attrs, nativeCellBorders: null }, afterAttrs = { ...next.attrs, nativeCellBorders: null }
  if (same(current.table.toJSON().content, next.content) && same(beforeAttrs, afterAttrs)) return false
  let tr = closeHistory(editor.state.tr)
  const map = TableMap.get(current.table)
  for (let r = 0; r < anchor.cells!.length; r++) for (let c = 0; c < anchor.cells![r]!.length; c++) {
    const cell = next.content![r]!.content![c]!, pos = current.pos + 1 + map.map[r * map.width + c]!
    if (!same(tr.doc.nodeAt(pos)!.attrs, cell.attrs)) tr = tr.setNodeMarkup(pos, undefined, cell.attrs)
  }
  tr = tr.setNodeMarkup(current.pos, undefined, next.attrs)
  if (editor.state.selection instanceof NodeSelection) tr = tr.setSelection(CellSelection.create(tr.doc, current.pos + 1 + map.map[0]!, current.pos + 1 + map.map[map.map.length - 1]!))
  editor.view.dispatch(tr)
  return true
}
/** 只投影已登记的边框意图，为独立shd差异提供可信baseline；终态仍须完整核验。 */
export function projectedDocxCellBordersBaseline(baseline: DocxPmNode, live: DocxPmNode, anchors: readonly DocxCellBordersAnchor[]): DocxPmNode {
  const projected = structuredClone(baseline)
  for (const table of live.content ?? []) if (table.type === 'docTable' && table.attrs?.nativeCellBorders != null) {
    const anchor = anchors.find(anchor => anchor.docxIndex === table.attrs!.docxIndex)
    const source = projected.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === table.attrs!.docxIndex)
    if (!anchor || !source) fail()
    projected.content![projected.content!.indexOf(source)] = project(source, safeDocxCellBorderSteps(table.attrs.nativeCellBorders), anchor)
  }
  return projected
}
export function normalizeDocxCellBorders(baseline: DocxPmNode, live: DocxPmNode, anchors: readonly DocxCellBordersAnchor[]) {
  const current = structuredClone(live), operations: DocxCellBordersOperation[] = []
  for (const table of current.content ?? []) if (table.type === 'docTable' && table.attrs?.nativeCellBorders != null) {
    const anchor = anchors.find(anchor => anchor.docxIndex === table.attrs!.docxIndex), source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === table.attrs!.docxIndex)
    if (!anchor || !source || table.attrs.nativeTableStructure || table.attrs.nativeTableInsert) fail()
    const steps = safeDocxCellBorderSteps(table.attrs.nativeCellBorders)
    if (!same(table, project(source, steps, anchor))) fail()
    current.content![current.content!.indexOf(table)] = structuredClone(source)
    operations.push({ kind: 'setTableCellBorders', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, steps })
  }
  return { baseline, current, operations }
}
export function replayDocxCellBorders(baseline: DocxPmNode, operations: readonly Record<string, any>[], anchors: readonly DocxCellBordersAnchor[]): DocxPmNode {
  const current = structuredClone(baseline), seen = new Set<string>()
  for (const operation of operations) if (operation.kind === 'setTableCellBorders') {
    if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || seen.has(operation.blockId)) fail()
    const anchor = anchors.find(anchor => anchor.blockId === operation.blockId)
    if (!anchor || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) fail()
    const table = current.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === anchor.docxIndex)
    if (!table) fail()
    seen.add(operation.blockId)
    current.content![current.content!.indexOf(table)] = project(table, safeDocxCellBorderSteps(operation.steps), anchor)
  }
  return current
}
