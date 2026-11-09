import { Extension, type Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { EditorState, TextSelection, NodeSelection } from '@tiptap/pm/state'
import type { Schema } from '@tiptap/pm/model'
import { TableMap, selectedRect, cellAround, CellSelection, addRowBefore, addRowAfter, deleteRow, addColumnBefore, addColumnAfter, deleteColumn } from '@tiptap/pm/tables'
import { restructuredTableTexts, type DocxAnchor, type DocxPmNode } from './docx-operations'

export const TABLE_KINDS = ['insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn'] as const
export type TableKind = typeof TABLE_KINDS[number]
export const TABLE_ACTIONS: Record<string, { kind: TableKind; after?: boolean }> = {
  'table-insert-row-before': { kind: 'insertTableRow' }, 'table-insert-row-after': { kind: 'insertTableRow', after: true },
  'table-insert-column-before': { kind: 'insertTableColumn' }, 'table-insert-column-after': { kind: 'insertTableColumn', after: true },
  'table-delete-row': { kind: 'deleteTableRow' }, 'table-delete-column': { kind: 'deleteTableColumn' },
}
// nativeTableInsert 标记新增表格的行列意图（docx-new-table.ts），与结构意图同样不渲染、不入文件。
// nativeCoverPage 标记新增封面首段的预设段落规格（docx-cover-page.ts），同样不渲染、不入文件。
export const NativeTableStructure = Extension.create({ name: 'nativeTableStructure', addGlobalAttributes: () => [
  { types: ['docTable'], attributes: { nativeTableStructure: { default: null, rendered: false }, nativeTableInsert: { default: null, rendered: false, keepOnSplit: false } } },
  { types: ['docParagraph'], attributes: { nativeCoverPage: { default: null, rendered: false, keepOnSplit: false } } },
] })
const sourceReason = (reason?: string | null) => {
  const messages: Record<string, string> = {
    width_unsupported: '仅支持宽度明确且一致的固定列宽表格', content_unsupported: '此表包含合并、嵌套、修订或其他暂不支持的内容',
    shell_unsupported: '此表含暂不能保留的表格或行列属性', properties_unsupported: '此表含暂不支持的结构属性',
    xml_unsupported: '此表含暂不支持的文档标记', size_unsupported: '此表超过支持的大小范围',
    header_unsupported: '此表的重复标题行不连续，暂不支持结构修改',
  }
  return reason?.startsWith('docx_table_structure_') ? messages[reason.slice('docx_table_structure_'.length)] ?? '当前来源表格暂不支持结构修改' : reason ?? '当前来源表格不支持结构编辑'
}
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
export function tableIntent(value: unknown): { kind: TableKind; index: number } {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !['kind', 'index'].includes(key))) throw new Error('表格结构草稿字段无效')
  const { kind, index } = value as { kind: TableKind; index: number }
  if (!TABLE_KINDS.includes(kind) || !Number.isInteger(index)) throw new Error('表格结构操作或源坐标无效')
  return { kind, index }
}
export type TableStep = { kind: TableKind; index: number }
export const MAX_TABLE_STEPS = 50
/** `{steps}` intent (multi-step, current protocol) or a legacy single `{kind, index}` draft intent. */
export function tableSteps(value: unknown): TableStep[] {
  if (value && typeof value === 'object' && !Array.isArray(value) && 'steps' in value) {
    const steps = (value as { steps: unknown }).steps
    if (Object.keys(value).length !== 1 || !Array.isArray(steps) || !steps.length || steps.length > MAX_TABLE_STEPS) throw new Error('表格结构草稿字段无效')
    return steps.map(tableIntent)
  }
  return [tableIntent(value)]
}
interface Projection { table: DocxPmNode; widths: number[]; headerCount: number; origin: ({ row: number; column: number } | null)[][] }
/** One upstream PM structure command over the current projection; surviving cells keep their content. */
function projectStep(current: Projection, step: TableStep, schema: Schema): Projection {
  const { kind, index } = step, rows = current.table.content ?? [], widths = [...current.widths]
  const rowOperation = kind.endsWith('Row'), inserting = kind.startsWith('insert'), count = rowOperation ? rows.length : widths.length
  if (index < 0 || index >= count + Number(inserting)) throw new Error('表格源坐标越界')
  if (!inserting && count === 1) throw new Error('不能删除最后一行或最后一列')
  const nextRows = rows.length + (rowOperation ? inserting ? 1 : -1 : 0), nextCols = widths.length + (!rowOperation ? inserting ? 1 : -1 : 0)
  if (nextRows > 100 || nextCols > 30 || nextRows * nextCols > 1000) throw new Error('表格结构超过支持的行列预算')
  const rowIds: (number | null)[] = rows.map((_, i) => i), colIds: (number | null)[] = widths.map((_, i) => i)
  const ids = rowOperation ? rowIds : colIds
  inserting ? ids.splice(index, 0, null) : ids.splice(index, 1)
  if (!rowOperation) {
    if (inserting) {
      const neighbor = Math.min(index, count - 1), width = widths[neighbor]!
      if (width < 2) throw new Error('相邻列宽太小，无法拆分插入列')
      widths.splice(neighbor, 1, Math.floor(width / 2), width - Math.floor(width / 2))
    } else { const [removed] = widths.splice(index, 1); widths[Math.min(index, widths.length - 1)]! += removed! }
  }
  const doc = schema.nodeFromJSON({ type: 'doc', content: [current.table] }), map = TableMap.get(doc.firstChild!)
  const row = rowOperation ? Math.min(index, count - 1) : 0, col = rowOperation ? 0 : Math.min(index, count - 1)
  let state = EditorState.create({ schema, doc, selection: TextSelection.near(doc.resolve(2 + map.map[row * map.width + col]!)) })
  const command = rowOperation ? inserting ? index === count ? addRowAfter : addRowBefore : deleteRow
    : inserting ? index === count ? addColumnAfter : addColumnBefore : deleteColumn
  if (!command(state, tr => { state = state.apply(tr) })) throw new Error('表格结构命令无法应用')
  const projected = state.doc.firstChild!.toJSON() as DocxPmNode
  if (projected.content?.length !== nextRows || projected.content.some(row => row.content?.length !== nextCols)) throw new Error('表格结构命令结果不一致')
  const total = widths.reduce((a, b) => a + b, 0)
  const newHeader = rowOperation && inserting && index < current.headerCount
  projected.attrs = { ...current.table.attrs, colWidthsPct: widths.map(width => width / total * 100) }
  projected.content = projected.content.map((row, ri) => {
    const sourceRow = rowIds[ri]!
    const attrs = sourceRow === null ? { ...schema.nodes.docTableRow.create().attrs, repeatHeader: newHeader, rawTrPr: newHeader ? '<w:trPr><w:tblHeader/></w:trPr>' : null } : rows[sourceRow]!.attrs
    return { ...row, attrs, content: row.content!.map((_, ci) => {
      const sourceColumn = colIds[ci]!
      const cell = sourceRow === null || sourceColumn === null
        ? schema.nodes.docTableCell.createAndFill()!.toJSON() as DocxPmNode
        : structuredClone(rows[sourceRow]!.content![sourceColumn]!)
      cell.attrs = { ...cell.attrs, colwidth: [Math.max(1, Math.round(widths[ci]! / 15))] }
      return cell
    }) }
  })
  const headerCount = current.headerCount + (newHeader ? 1 : 0) - (rowOperation && !inserting && index < current.headerCount ? 1 : 0)
  return { table: projected, widths, headerCount,
    origin: rowIds.map(r => colIds.map(c => r === null || c === null ? null : current.origin[r]?.[c] ?? null)) }
}
function projectSteps(source: DocxPmNode, anchor: DocxAnchor, steps: readonly TableStep[], schema?: Schema): Projection {
  if (!schema || source.type !== 'docTable' || !anchor.structureEditable) throw new Error(sourceReason(anchor.structureReadOnlyReason))
  const widths = [...(anchor.tableWidthsTwips ?? [])], rows = source.content ?? []
  if (!widths.length || rows.length !== anchor.cells?.length || rows.some(row => row.content?.length !== widths.length)
    || widths.some(width => !Number.isInteger(width) || width < 1)) throw new Error('表格源宽度或坐标不一致')
  let current: Projection = { table: source, widths, headerCount: anchor.tableHeaderCount ?? 0, origin: rows.map((row, r) => (row.content ?? []).map((_, c) => ({ row: r, column: c }))) }
  for (const step of steps) current = projectStep(current, step, schema)
  return current
}
/** Deterministic projection of the source table through ordered steps (attr carries the intent). */
export function projectDocxTableSteps(source: DocxPmNode, anchor: DocxAnchor, steps: readonly TableStep[], schema?: Schema, legacy = false): DocxPmNode {
  const { table } = projectSteps(source, anchor, steps, schema)
  table.attrs = { ...table.attrs, nativeTableStructure: legacy ? steps[0] : { steps } }
  return schema!.nodeFromJSON(table).toJSON() as DocxPmNode
}
/** Next step on the live table: earlier steps' projection supplies widths/header
 *  prefix, the live cells (with their text edits) carry over through the step. */
export function extendDocxTable(source: DocxPmNode, anchor: DocxAnchor, live: DocxPmNode, steps: readonly TableStep[], step: TableStep, schema: Schema): DocxPmNode {
  const base = projectSteps(source, anchor, steps, schema)
  const next = projectStep({ ...base, table: live }, step, schema)
  next.table.attrs = { ...next.table.attrs, nativeTableStructure: { steps: [...steps, step] } }
  return schema.nodeFromJSON(next.table).toJSON() as DocxPmNode
}
/** Legacy single-step projection (drafts saved before multi-step tables). */
export function projectDocxTable(source: DocxPmNode, anchor: DocxAnchor, value: unknown, schema?: Schema): DocxPmNode {
  return projectDocxTableSteps(source, anchor, [tableIntent(value)], schema, true)
}
export interface DocxTableCommands { reason: (action: string) => string | null; run: (action: string) => void }
export function createDocxTableCommands(editor: Editor, baseline: DocxPmNode, anchors: DocxAnchor[], reportError: (error: unknown) => void): DocxTableCommands {
  const target = (action: string) => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    const spec = TABLE_ACTIONS[action]
    if (!spec) throw new Error('此表格命令尚未接入')
    const selection = editor.state.selection
    if (selection instanceof NodeSelection || (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos)) throw new Error('请在单个单元格内选择插入或删除位置')
    const rect = selectedRect(editor.state)
    if (rect.right - rect.left !== 1 || rect.bottom - rect.top !== 1) throw new Error('请在单个单元格内选择插入或删除位置')
    const index = rect.table.attrs.docxIndex
    const anchor = anchors.find(anchor => anchor.docxIndex === index)
    const source = baseline.content?.find(node => node.attrs?.docxIndex === index)
    if (!source || !anchor?.structureEditable) throw new Error(sourceReason(anchor?.structureReadOnlyReason))
    // 已有步骤（含旧草稿单步意图）继续累加；同表此前只允许文字修改（与投影逐格比对）。
    const intent = rect.table.attrs.nativeTableStructure
    const steps = intent ? tableSteps(intent) : []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表结构修改步骤过多，请先保存')
    const live = rect.table.toJSON() as DocxPmNode
    restructuredTableTexts(steps.length ? projectDocxTableSteps(source, anchor, steps, editor.schema) : source, live)
    const coordinate = (spec.kind.endsWith('Row') ? rect.top : rect.left) + Number(!!spec.after)
    const step = { kind: spec.kind, index: coordinate }
    return { anchor, rect, step, projected: extendDocxTable(source, anchor, live, steps, step, editor.schema) }
  }
  return {
    reason(action) { try { target(action); return null } catch (error) { return error instanceof Error && !/No cell|Not in a table/.test(error.message) ? error.message : '请先在可编辑表格的单个单元格内定位' } },
    run(action) {
      try {
        const { rect, projected, step: intent } = target(action)
        const table = editor.schema.nodeFromJSON(projected), map = TableMap.get(table), start = rect.tableStart - 1
        const row = Math.min(intent.kind === 'insertTableRow' ? intent.index : rect.top, map.height - 1)
        const column = Math.min(intent.kind === 'insertTableColumn' ? intent.index : rect.left, map.width - 1)
        const tr = editor.state.tr.replaceWith(start, start + rect.table.nodeSize, table)
        tr.setSelection(TextSelection.near(tr.doc.resolve(start + 2 + map.map[row * map.width + column]!)))
        editor.view.dispatch(closeHistory(tr)); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
      } catch (error) { reportError(error) }
    },
  }
}
