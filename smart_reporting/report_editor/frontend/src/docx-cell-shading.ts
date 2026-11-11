import type { Editor } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import { CellSelection, TableMap, isInTable, selectionCell } from '@tiptap/pm/tables'
import type { DocxPmNode } from './docx-operations'

export interface DocxCellShadingAnchor {
  docxIndex: number; blockId: string
  cells?: { cellId: string; expectedObjectSha256: string; shadingEditable?: boolean; shadingReadOnlyReason?: string }[][]
}
export interface DocxCellShadingOperation { [key: string]: unknown; kind: 'setCellShading'; blockId: string; cellId: string; expectedObjectSha256: string; fill: string | null }
function fail(): never { throw new Error('单元格底纹来源或草稿无效；合并、嵌套、修订及同单元格正文/结构混合修改暂不支持') }
export function safeDocxCellFill(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !/^[0-9a-fA-F]{6}$/.test(value)) fail()
  return value.toUpperCase()
}
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const tableOf = (doc: DocxPmNode, index: number) => doc.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
const fillOf = (node: DocxPmNode) => node.attrs?.fill ?? null
/** 先归一底纹，再交回普通正文diff；rich cell不能因text editable=false被误拦。 */
export function normalizeDocxCellShading(baseline: DocxPmNode, live: DocxPmNode, anchors: readonly DocxCellShadingAnchor[]) {
  const current = structuredClone(live), operations: DocxCellShadingOperation[] = []
  for (const anchor of anchors) {
    const source = tableOf(baseline, anchor.docxIndex), table = tableOf(current, anchor.docxIndex)
    if (!source || !table) continue
    for (const [r, row] of (source.content ?? []).entries()) for (const [c, original] of (row.content ?? []).entries()) {
      const cell = table.content?.[r]?.content?.[c]
      if (!cell || same(fillOf(cell), fillOf(original))) continue
      const identity = anchor.cells?.[r]?.[c]
      if (!identity?.shadingEditable || !same(source.attrs, table.attrs) || source.content?.length !== table.content?.length || row.content?.length !== table.content?.[r]?.content?.length) fail()
      const fill = safeDocxCellFill(fillOf(cell))
      const normalized = structuredClone(cell)
      if (original.attrs && Object.hasOwn(original.attrs, 'fill')) normalized.attrs = { ...normalized.attrs, fill: original.attrs.fill }
      else if (normalized.attrs) delete normalized.attrs.fill
      if (!same(normalized, original)) fail()
      table.content![r]!.content![c] = normalized
      operations.push({ kind: 'setCellShading', blockId: anchor.blockId, cellId: identity.cellId, expectedObjectSha256: identity.expectedObjectSha256, fill })
    }
  }
  return { baseline, current, operations }
}
export function replayDocxCellShading(baseline: DocxPmNode, operations: readonly Record<string, any>[], anchors: readonly DocxCellShadingAnchor[]): DocxPmNode {
  const current = structuredClone(baseline), seen = new Set<string>()
  for (const op of operations) {
    if (op.kind !== 'setCellShading') continue
    if (Object.keys(op).some(key => !['kind', 'blockId', 'cellId', 'expectedObjectSha256', 'fill'].includes(key))) fail()
    const anchor = anchors.find(anchor => anchor.blockId === op.blockId), table = anchor && tableOf(current, anchor.docxIndex)
    let found = false
    for (const [r, row] of (anchor?.cells ?? []).entries()) for (const [c, identity] of row.entries()) if (identity.cellId === op.cellId) {
      if (found || seen.has(identity.cellId) || !identity.shadingEditable || identity.expectedObjectSha256 !== op.expectedObjectSha256) fail()
      const cell = table?.content?.[r]?.content?.[c]
      if (!cell) fail()
      cell.attrs = { ...cell.attrs, fill: safeDocxCellFill(op.fill) }
      seen.add(identity.cellId); found = true
    }
    if (!found) fail()
  }
  return current
}
/** 固定源：整表NodeSelection→全部cells；selectionCell已有目标色则整次no-op。 */
export function applyDocxCellShading(editor: Editor, value: unknown, anchors: readonly DocxCellShadingAnchor[]): boolean {
  const fill = safeDocxCellFill(value)
  if (!editor.isEditable) return false
  editor.view.focus()
  let state = editor.state
  if (state.selection instanceof NodeSelection && state.selection.node.type.name === 'docTable') {
    const map = TableMap.get(state.selection.node), start = state.selection.from + 1
    editor.view.dispatch(state.tr.setSelection(CellSelection.create(state.doc, start + map.map[0]!, start + map.map[map.map.length - 1]!)))
    state = editor.state
  }
  if (!isInTable(state)) return false
  const selected = selectionCell(state)
  if ((selected.nodeAfter!.attrs.fill ?? null) === fill) return false
  let depth = selected.depth
  while (depth > 0 && selected.node(depth).type.name !== 'docTable') depth--
  if (!depth) fail()
  const table = selected.node(depth), start = selected.start(depth), map = TableMap.get(table)
  const anchor = anchors.find(anchor => anchor.docxIndex === table.attrs.docxIndex)
  if (!anchor || table.attrs.nativeTableStructure || table.attrs.nativeTableInsert) fail()
  const targets: { pos: number; node: typeof table }[] = []
  if (state.selection instanceof CellSelection) state.selection.forEachCell((node, pos) => targets.push({ pos, node }))
  else targets.push({ pos: selected.pos, node: selected.nodeAfter! })
  for (const target of targets) {
    const rect = map.findCell(target.pos - start)
    if (!anchor.cells?.[rect.top]?.[rect.left]?.shadingEditable) fail()
  }
  const tr = state.tr
  for (const { pos, node } of targets) if (node.attrs.fill !== fill) tr.setNodeMarkup(pos, null, { ...node.attrs, fill })
  editor.view.dispatch(tr)
  return true
}
/** 色板可用性只读预检；整表选择逐cell核验，不能复用正文/结构编辑门禁。 */
export function docxCellShadingUnavailable(editor: Editor, anchors: readonly DocxCellShadingAnchor[]): string | null {
  if (!editor.isEditable) return '当前文档只读'
  let state = editor.state
  if (state.selection instanceof NodeSelection && state.selection.node.type.name === 'docTable') {
    const map = TableMap.get(state.selection.node), start = state.selection.from + 1
    state = state.apply(state.tr.setSelection(CellSelection.create(state.doc, start + map.map[0]!, start + map.map[map.map.length - 1]!)))
  }
  if (!isInTable(state)) return '请先选择表格中的单元格'
  const selected = selectionCell(state)
  let depth = selected.depth
  while (depth > 0 && selected.node(depth).type.name !== 'docTable') depth--
  if (!depth) return '无法核验所选单元格来源'
  const table = selected.node(depth), map = TableMap.get(table), start = selected.start(depth)
  if (table.attrs.nativeTableStructure || table.attrs.nativeTableInsert) return '请先保存表格结构修改，再调整单元格底纹'
  const anchor = anchors.find(anchor => anchor.docxIndex === table.attrs.docxIndex)
  let reason: string | null = null
  const check = (pos: number) => {
    const rect = map.findCell(pos - start), identity = anchor?.cells?.[rect.top]?.[rect.left]
    if (!identity?.shadingEditable && reason === null) reason = identity?.shadingReadOnlyReason ?? '此单元格包含合并、嵌套、修订或不明确的来源，暂不能修改底纹'
  }
  if (state.selection instanceof CellSelection) state.selection.forEachCell((_node, pos) => check(pos))
  else check(selected.pos)
  return reason
}
