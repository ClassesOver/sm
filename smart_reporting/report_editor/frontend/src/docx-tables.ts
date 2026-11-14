import { projectDocxTableProperties, tablePropertiesPatchOf } from './docx-table-properties'
import { openDocxTablePropertiesSourceDialog } from './docx-table-properties-source'
import {projectDocxTableAltText,type DocxTableAltTextAnchor} from './docx-table-alt-text'
import {normalizeTableAltText} from './docx-table-alt-text-core'
import {openDocxTableAltTextDialog,attachDocxTableAltTextNavigation} from './docx-table-alt-text-controls'
import {projectDocxCellWrap,type DocxCellWrapAnchor} from './docx-table-cell-wrap'
import type {TableCellWrapStep} from './docx-table-cell-wrap-core'
import {openDocxCellWrapDialog,attachDocxCellWrapNavigation} from './docx-table-cell-wrap-controls'
import { projectDocxTableAlignment, type DocxTableAlignmentAnchor } from './docx-table-alignment'
import { applyDocxTableStyle, docxTableStyleActive, docxTableStyleUnavailable, isDocxTableStyleAction, docxTableStyleOptionsAt, openDocxTableStyleGallery } from './docx-table-style'
import { openDocxTableAlignmentDialog, type DocxTableAlignment } from './docx-table-alignment-controls'
import { projectDocxRowBreaks, type DocxRowBreakAnchor } from './docx-table-row-breaks'
import type { TableRowBreakStep } from './docx-table-row-breaks-core'
import { openDocxRowBreaksDialog, openDocxRowPropertiesMenu } from './docx-table-row-breaks-controls'
import { projectDocxCellMarginOverrides, type DocxCellMarginOverridesAnchor } from './docx-table-cell-margin-overrides'
import { replayTableCellMarginOverrides, type TableCellMarginOverrideStep } from './docx-table-cell-margin-overrides-core'
import { openDocxCellMarginOverridesDialog } from './docx-table-cell-margin-overrides-controls'
import { projectDocxCellMargins, type DocxCellMarginsAnchor } from './docx-table-cell-margins'
import { openDocxCellMarginsDialog } from './docx-table-cell-margins-controls'
import { projectDocxCellAlignment, type DocxCellAlignmentAnchor } from './docx-table-cell-alignment'
import { applyTableCellAlignmentSteps, type TableCellAlignmentStep } from './docx-table-cell-alignment-core'
import { projectDocxCellTextDirection, type DocxCellTextDirectionAnchor } from './docx-table-cell-text-direction'
import type { TableCellTextDirectionStep } from './docx-table-cell-text-direction-core'
import { projectDocxAutoFit, type DocxAutoFitAnchor } from './docx-table-autofit'
import type { TableAutoFitStep } from './docx-table-autofit-core'
import { measureDocxRowHeight } from './docx-table-row-height-measure'
import { projectDocxRowHeights, type DocxRowHeightAnchor } from './docx-table-row-height'
import { openDocxRowHeightDialog } from './docx-table-row-height-controls'
import type { TableRowHeightStep } from './docx-table-row-height-core'
import { tableHeaderOperation } from './docx-table-headers'
import { Extension, type Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { EditorState, TextSelection, NodeSelection, Selection } from '@tiptap/pm/state'
import type { Schema } from '@tiptap/pm/model'
import { TableMap, selectedRect, cellAround, CellSelection, addRowBefore, addRowAfter, deleteRow, addColumnBefore, addColumnAfter, deleteColumn } from '@tiptap/pm/tables'
import { restructuredTableTexts, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { projectDocxCellShape } from './docx-table-cell-shape'
import type { TableCellShapeStep } from './docx-table-cell-shape-core'
import { projectDocxColumnWidths, type DocxColumnWidthAnchor } from './docx-table-column-width'
import type { TableColumnWidthStep } from './docx-table-column-width-core'
import { openDocxColumnWidthDialog } from './docx-table-column-width-controls'
import { openDocxCellSplitDialog } from './docx-table-cell-shape-controls'

export const TABLE_KINDS = ['insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn'] as const
export type TableKind = typeof TABLE_KINDS[number]
export const TABLE_ACTIONS: Record<string, { kind: TableKind; after?: boolean }> = {
  'table-insert-row-before': { kind: 'insertTableRow' }, 'table-insert-row-after': { kind: 'insertTableRow', after: true },
  'table-insert-column-before': { kind: 'insertTableColumn' }, 'table-insert-column-after': { kind: 'insertTableColumn', after: true },
  'table-delete-row': { kind: 'deleteTableRow' }, 'table-delete-column': { kind: 'deleteTableColumn' },
}
export const TABLE_SELECTION_ACTIONS: Record<string, 'cell' | 'row' | 'column' | 'table'> = {
  'table-select-cell': 'cell', 'table-select-row': 'row', 'table-select-column': 'column', 'table-select-all': 'table',
}
// nativeTableInsert 标记新增表格的行列意图（docx-new-table.ts），与结构意图同样不渲染、不入文件。
// nativeCoverPage 标记新增封面首段的预设段落规格（docx-cover-page.ts），同样不渲染、不入文件。
export const NativeTableStructure = Extension.create({ name: 'nativeTableStructure', addGlobalAttributes: () => [
  { types: ['docParagraph', 'docHeading', 'docListItem'], attributes: { nativeClearFormatting: { default: null, rendered: false, keepOnSplit: false } } },
  { types: ['docTable'], attributes: { nativeTableProperties: { default: null, rendered: false }, nativeTableStructure: { default: null, rendered: false }, nativeTableCellShape: { default: null, rendered: false }, nativeTableColumnWidths: { default: null, rendered: false }, nativeTableRowHeights: { default: null, rendered: false }, nativeTableAutoFit: { default: null, rendered: false }, nativeTableCellTextDirection: { default: null, rendered: false }, nativeTableCellAlignment: { default: null, rendered: false }, nativeTableCellParagraphProperties: { default: null, rendered: false }, nativeTableCellMargins: { default: null, rendered: false }, nativeTableCellWrap: { default: null, rendered: false }, nativeTableAltText: { default: null, rendered: false }, nativeTableCellMarginOverrides: { default: null, rendered: false }, nativeTableRowBreaks: { default: null, rendered: false }, nativeTableAlignment: { default: null, rendered: false }, nativeTableStyle: { default: null, rendered: false }, nativeTableInsert: { default: null, rendered: false, keepOnSplit: false } } },
  { types: ['docParagraph'], attributes: { nativeCoverPage: { default: null, rendered: false, keepOnSplit: false } } },
  // nativeSectionBreak 标记新增分节符的起始方式（docx-operations.ts sectionBreakNode），同样不渲染、不入文件。
  { types: ['docProtected'], attributes: { nativeSectionBreak: { default: null, rendered: false, keepOnSplit: false } } },
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
export interface DocxTableCommands { active?: (action: string) => boolean; reason: (action: string) => string | null; run: (action: string) => void }
export function createDocxTableCommands(editor: Editor, baseline: DocxPmNode, anchors: DocxAnchor[], reportError: (error: unknown) => void, nestedInputActive: () => boolean = () => false): DocxTableCommands {
  const selectionTarget = () => {
    if (nestedInputActive()) throw new Error('嵌套表格输入中，请先在外层表格内定位')
    const selection = editor.state.selection
    if (selection instanceof NodeSelection && selection.node.type.name === 'docTable') {
      return { table: selection.node, tablePos: selection.from, map: TableMap.get(selection.node), top: 0, left: 0 }
    }
    const rect = selectedRect(editor.state)
    return { table: rect.table, tablePos: rect.tableStart - 1, map: rect.map, top: rect.top, left: rect.left }
  }
  const selectTablePart = (action: string) => {
    const target = selectionTarget(), kind = TABLE_SELECTION_ACTIONS[action]
    if (!kind) throw new Error('此表格选择命令尚未接入')
    if (kind === 'table') {
      editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, target.tablePos)))
      return
    }
    const cellPos = target.tablePos + 1 + target.map.map[target.top * target.map.width + target.left]!
    const $cell = editor.state.doc.resolve(cellPos)
    const selection = kind === 'row' ? CellSelection.rowSelection($cell)
      : kind === 'column' ? CellSelection.colSelection($cell) : new CellSelection($cell)
    editor.view.dispatch(editor.state.tr.setSelection(selection))
  }
  const target = (action: string) => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后操作结构或标题行')
    const spec = TABLE_ACTIONS[action]
    if (!spec) throw new Error('此表格命令尚未接入')
    const selection = editor.state.selection
    if (selection instanceof NodeSelection || (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos)) throw new Error('请在单个单元格内选择插入或删除位置')
    const rect = selectedRect(editor.state)
    if (rect.table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellAlignment) throw new Error('单元格对齐修改后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellTextDirection) throw new Error('文字方向修改后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableAutoFit) throw new Error('自动调整后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableRowHeights) throw new Error('行高调整后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableColumnWidths) throw new Error('列宽调整后不能与同表行列增删混用，请先保存')
    if (rect.table.attrs.nativeTableCellShape) throw new Error('合并拆分后不能与同表行列增删混用，请先保存')
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
  const headerTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后操作结构或标题行')
    const rect=selectedRect(editor.state)
    if (rect.table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if(rect.table.attrs.nativeTableCellMargins)throw new Error('默认边距修改后不能与同表重复标题行混用，请先保存')
    if(rect.table.attrs.nativeTableCellAlignment)throw new Error('单元格对齐修改后不能与同表重复标题行混用，请先保存')
    if(rect.table.attrs.nativeTableCellTextDirection)throw new Error('文字方向修改后不能与同表重复标题行混用，请先保存')
    if(rect.table.attrs.nativeTableAutoFit)throw new Error('自动调整后不能与同表重复标题行混用，请先保存')
    if(rect.table.attrs.nativeTableRowHeights)throw new Error('行高调整后不能与同表重复标题行混用，请先保存')
    if(rect.table.attrs.nativeTableColumnWidths)throw new Error('列宽调整后不能与同表重复标题行混用，请先保存')
    if(rect.table.attrs.nativeTableCellShape)throw new Error('合并拆分后不能与同表重复标题行混用，请先保存')
    if(rect.top!==0)throw new Error('请从表格首行选择重复标题行')
    const index=rect.table.attrs.docxIndex,anchor=anchors.find(anchor=>anchor.docxIndex===index)
    const source=baseline.content?.find(node=>node.type==='docTable'&&node.attrs?.docxIndex===index)
    if(!source||!anchor||source.content?.length!==rect.table.childCount)throw new Error('来源表格身份或行数已改变，请先保存')
    tableHeaderOperation(source,rect.table.toJSON() as DocxPmNode,anchor)
    // 与源toggleRepeatHeaderRows相同：选中前缀全为标题则关闭，否则全部打开。
    let active=true;for(let row=0;row<rect.bottom;row++)if(!rect.table.child(row).attrs.repeatHeader)active=false
    return {rect,active}
  }
  const shapeTarget = (action: string) => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后合并或拆分')
    const selection = editor.state.selection
    if (selection instanceof NodeSelection || (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos)) throw new Error('请在单元格内定位或选择完整矩形单元格')
    if (action === 'table-merge-cells' && (!(selection instanceof CellSelection) || selection.$anchorCell.pos === selection.$headCell.pos)) throw new Error('请选中需要合并的完整矩形单元格')
    const rect = selectedRect(editor.state), index = rect.table.attrs.docxIndex
    if (rect.table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellAlignment) throw new Error('单元格对齐修改后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableCellTextDirection) throw new Error('文字方向修改后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableAutoFit) throw new Error('自动调整后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableRowHeights) throw new Error('行高调整后不能与同表其他结构修改混用，请先保存')
    if (rect.table.attrs.nativeTableColumnWidths) throw new Error('列宽调整后不能与同表合并拆分混用，请先保存')
    const anchor = anchors.find(item => item.docxIndex === index), source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.cellShapeEditable) throw new Error(anchor?.cellShapeReadOnlyReason ?? '当前来源表格不支持合并或拆分')
    const intent = rect.table.attrs.nativeTableCellShape as { steps: TableCellShapeStep[] } | null
    const steps = intent?.steps ?? []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表合并拆分步骤过多，请先保存')
    if (!equal(rect.table.toJSON(), steps.length ? projectDocxCellShape(source, anchor, steps, editor.schema) : source)) throw new Error('合并拆分不能与同表文字、格式、标题行或其他结构修改混用，请先保存')
    const logical = { top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right }
    // 每个已选 span 必须完整包含在矩形内；不能截断既有合并格。
    for (const pos of rect.map.cellsInRect(logical)) {
      const cell = rect.map.findCell(pos)
      if (cell.top < logical.top || cell.left < logical.left || cell.bottom > logical.bottom || cell.right > logical.right) throw new Error('请选择完整矩形单元格，不能截断已有合并格')
    }
    return { rect, source, anchor, steps, logical }
  }
  const applyShape = (action: string, split?: { rows: number; columns: number; mergeFirst: boolean }, expected?: DocxPmNode) => {
    const { rect, source, anchor, steps, logical } = shapeTarget(action)
    if (expected && !equal(expected, editor.getJSON())) throw new Error('拆分对话框打开后文档已改变，请重新选择')
    const step: TableCellShapeStep = split ? { kind: 'splitTableCells', rect: logical, ...split } : { kind: 'mergeTableCells', rect: logical }
    const table = editor.schema.nodeFromJSON(projectDocxCellShape(source, anchor, [...steps, step], editor.schema)), start = rect.tableStart - 1
    const map = TableMap.get(table), tr = closeHistory(editor.state.tr).replaceWith(start, start + rect.table.nodeSize, table)
    tr.setSelection(TextSelection.near(tr.doc.resolve(start + 2 + map.map[logical.top * map.width + logical.left]!)))
    editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
  }
  const widthTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后调整列宽')
    const selection = editor.state.selection
    let table, tableStart: number, left: number, right: number
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1; left = 0; right = TableMap.get(table).width
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格或逻辑列')
      const rect = selectedRect(editor.state)
      table = rect.table; tableStart = rect.tableStart; left = rect.left; right = rect.right
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellAlignment) throw new Error('单元格对齐修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellTextDirection) throw new Error('文字方向修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableAutoFit) throw new Error('自动调整后不能与同表列宽混用，请先保存')
    if (table.attrs.nativeTableRowHeights) throw new Error('行高调整后不能与同表列宽混用，请先保存')
    const index = table.attrs.docxIndex
    const anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxColumnWidthAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.columnWidthEditable) throw new Error(anchor?.columnWidthReadOnlyReason ?? '当前来源表格不支持调整列宽')
    const intent = table.attrs.nativeTableColumnWidths as { steps: TableColumnWidthStep[] } | null
    const steps = intent?.steps ?? []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表列宽修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxColumnWidths(source, anchor, steps, editor.schema) : source)) throw new Error('列宽不能与同表文字、格式、合并拆分、标题行或其他结构修改混用，请先保存')
    return { table, tableStart, left, right, anchor, source, steps }
  }
  const applyWidth = (widthTwips?: number, frozen?: { doc: DocxPmNode; selection: unknown }) => {
    const target = widthTarget()
    if (frozen && (!equal(frozen.doc, editor.getJSON()) || !equal(frozen.selection, editor.state.selection.toJSON()))) throw new Error('列宽对话框打开后文档或选区已改变，请重新选择')
    const { table, tableStart, left, right, anchor, source, steps } = target
    const step: TableColumnWidthStep = widthTwips === undefined ? { kind: 'distributeTableColumns', left, right } : { kind: 'setTableColumnWidth', left, right, widthTwips }
    const projected = editor.schema.nodeFromJSON(projectDocxColumnWidths(source, anchor, [...steps, step], editor.schema))
    const tr = closeHistory(editor.state.tr).replaceWith(tableStart - 1, tableStart - 1 + table.nodeSize, projected)
    // 宽度不改节点大小；保留完整选区以便下一步按同一逻辑列继续操作。
    tr.setSelection(Selection.fromJSON(tr.doc, editor.state.selection.toJSON()))
    editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
  }
  const heightTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后调整行高')
    const selection = editor.state.selection
    let table, tableStart: number, top: number, bottom: number
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1; top = 0; bottom = table.childCount
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格或逻辑行')
      const rect = selectedRect(editor.state)
      table = rect.table; tableStart = rect.tableStart; top = rect.top; bottom = rect.bottom
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellAlignment) throw new Error('单元格对齐修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellTextDirection) throw new Error('文字方向修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableAutoFit) throw new Error('自动调整后不能与同表行高混用，请先保存')
    const index = table.attrs.docxIndex
    const anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxRowHeightAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.rowHeightEditable) throw new Error(anchor?.rowHeightReadOnlyReason ?? '当前来源表格不支持调整行高')
    const steps = (table.attrs.nativeTableRowHeights as { steps: TableRowHeightStep[] } | null)?.steps ?? []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表行高修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxRowHeights(source, anchor, steps, editor.schema) : source)) throw new Error('行高不能与同表文字、格式、列宽或其他结构修改混用，请先保存')
    return { table, tableStart, top, bottom, anchor, source, steps }
  }
  const commitHeight = (target: ReturnType<typeof heightTarget>, step: TableRowHeightStep) => {
    const { table, tableStart, anchor, source, steps } = target
    const projected = editor.schema.nodeFromJSON(projectDocxRowHeights(source, anchor, [...steps, step], editor.schema))
    const tr = closeHistory(editor.state.tr).replaceWith(tableStart - 1, tableStart - 1 + table.nodeSize, projected)
    tr.setSelection(Selection.fromJSON(tr.doc, editor.state.selection.toJSON()))
    editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
  }
  const applyHeight = (heightTwips: number | null, frozen: { doc: DocxPmNode; selection: unknown }) => {
    const target = heightTarget()
    if (!equal(frozen.doc, editor.getJSON()) || !equal(frozen.selection, editor.state.selection.toJSON())) throw new Error('行高对话框打开后文档或选区已改变，请重新选择')
    commitHeight(target, { top: target.top, bottom: target.bottom, heightTwips })
  }
  const distributeHeight = async () => {
    const target = heightTarget(), doc = editor.state.doc, selection = editor.state.selection.toJSON()
    const top = target.bottom - target.top === 1 ? 0 : target.top
    const bottom = target.bottom - target.top === 1 ? target.table.childCount : target.bottom
    const current = () => editor.isEditable && !editor.isDestroyed && !nestedInputActive() && editor.state.doc === doc && equal(editor.state.selection.toJSON(), selection)
    const heightTwips = await measureDocxRowHeight(editor.view, target.table, target.tableStart, top, bottom, current)
    if (!current()) throw new Error('均分行高准备期间文档或选区已改变，请重试')
    commitHeight(heightTarget(), { kind: 'distributeTableRows', top, bottom, heightTwips })
  }
  const autoFitModes: Record<string, TableAutoFitStep['mode']> = { 'table-autofit-contents': 'contents', 'table-autofit-window': 'window', 'table-autofit-fixed': 'fixed' }
  const autoFitTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后自动调整')
    const selection = editor.state.selection
    let table, tableStart: number
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格')
      const rect = selectedRect(editor.state); table = rect.table; tableStart = rect.tableStart
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellAlignment) throw new Error('单元格对齐修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellTextDirection) throw new Error('文字方向修改后不能与同表自动调整混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxAutoFitAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.autoFitEditable) throw new Error(anchor?.autoFitReadOnlyReason ?? '当前来源表格不支持自动调整列宽，请先保存新增表格')
    const steps = (table.attrs.nativeTableAutoFit as { steps: TableAutoFitStep[] } | null)?.steps ?? []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表自动调整步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxAutoFit(source, anchor, steps, editor.schema) : source)) throw new Error('自动调整不能与同表文字、格式、标题行、行高、列宽或其他结构修改混用，请先保存')
    return { table, tableStart, anchor, source, steps }
  }
  const applyAutoFit = (mode: TableAutoFitStep['mode']) => {
    const { table, tableStart, anchor, source, steps } = autoFitTarget()
    const projected = editor.schema.nodeFromJSON(projectDocxAutoFit(source, anchor, [...steps, { mode }], editor.schema))
    const tr = closeHistory(editor.state.tr).replaceWith(tableStart - 1, tableStart - 1 + table.nodeSize, projected)
    tr.setSelection(Selection.fromJSON(tr.doc, editor.state.selection.toJSON()))
    editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
  }
  const directionActions: Record<string, TableCellTextDirectionStep['direction']> = { 'table-text-direction-horizontal': 'lrTb', 'table-text-direction-rotate-90': 'tbRl', 'table-text-direction-rotate-270': 'btLr' }
  const directionTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层单元格内定位后修改文字方向')
    const selection = editor.state.selection
    let table, tableStart: number, rect: { top: number; left: number; bottom: number; right: number }
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1
      rect = { top: 0, left: 0, bottom: table.childCount, right: TableMap.get(table).width }
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格')
      const selected = selectedRect(editor.state); table = selected.table; tableStart = selected.tableStart
      rect = { top: selected.top, left: selected.left, bottom: selected.bottom, right: selected.right }
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表其他结构修改混用，请先保存')
    if (table.attrs.nativeTableCellAlignment) throw new Error('单元格对齐修改后不能与同表文字方向混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxCellTextDirectionAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.cellTextDirectionEditable) throw new Error(anchor?.cellTextDirectionReadOnlyReason ?? '当前来源表格不支持修改文字方向，请先保存新增表格')
    const steps = (table.attrs.nativeTableCellTextDirection as { steps: TableCellTextDirectionStep[] } | null)?.steps ?? []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表文字方向修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxCellTextDirection(source, anchor, steps, editor.schema) : source)) throw new Error('文字方向不能与同表文字、格式或其他结构修改混用，请先保存')
    return { table, tableStart, rect, anchor, source, steps }
  }
  const directionActive = (direction: TableCellTextDirectionStep['direction']) => {
    const { table, rect } = directionTarget(), map = TableMap.get(table), positions = new Set<number>()
    for (let row = rect.top; row < rect.bottom; row++) for (let column = rect.left; column < rect.right; column++) positions.add(map.map[row * map.width + column])
    return [...positions].every(pos => (table.nodeAt(pos)!.attrs.textDirection ?? null) === (direction === 'lrTb' ? null : direction))
  }
  const applyDirection = (direction: TableCellTextDirectionStep['direction']) => {
    const { table, tableStart, rect, anchor, source, steps } = directionTarget()
    const projected = editor.schema.nodeFromJSON(projectDocxCellTextDirection(source, anchor, [...steps, { ...rect, direction }], editor.schema))
    const tr = closeHistory(editor.state.tr).replaceWith(tableStart - 1, tableStart - 1 + table.nodeSize, projected)
    tr.setSelection(Selection.fromJSON(tr.doc, editor.state.selection.toJSON()))
    editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
  }
  const alignmentActions: Record<string, Pick<TableCellAlignmentStep, 'vertical' | 'horizontal'>> = {}
  for (const vertical of ['top', 'center', 'bottom'] as const) for (const horizontal of ['left', 'center', 'right'] as const) alignmentActions[`table-align-${vertical === 'center' ? 'middle' : vertical}-${horizontal}`] = { vertical, horizontal }
  const alignmentTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层单元格内定位后调整对齐')
    const selection = editor.state.selection
    let table, tableStart: number, rect: { top: number; left: number; bottom: number; right: number }
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1
      rect = { top: 0, left: 0, bottom: table.childCount, right: TableMap.get(table).width }
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格')
      const selected = selectedRect(editor.state); table = selected.table; tableStart = selected.tableStart
      rect = { top: selected.top, left: selected.left, bottom: selected.bottom, right: selected.right }
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMargins) throw new Error('默认边距修改后不能与同表对齐混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxCellAlignmentAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.cellAlignmentEditable) throw new Error(anchor?.cellAlignmentReadOnlyReason ?? '当前来源表格不支持单元格对齐，请先保存新增表格')
    const steps = (table.attrs.nativeTableCellAlignment as { steps: TableCellAlignmentStep[] } | null)?.steps ?? []
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表单元格对齐修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxCellAlignment(source, anchor, steps, editor.schema) : source)) throw new Error('单元格对齐不能与同表文字、格式或其他结构修改混用，请先保存')
    return { table, tableStart, rect, anchor, source, steps }
  }
  const alignmentActive = (alignment: Pick<TableCellAlignmentStep, 'vertical' | 'horizontal'>) => {
    const { table, rect } = alignmentTarget()
    // 使用同一来源投影判断是否全选区已对齐，复用RTL/null与直属类型规则。
    return applyTableCellAlignmentSteps(table, [{ ...rect, ...alignment }]).table.eq(table)
  }
  const applyAlignment = (alignment: Pick<TableCellAlignmentStep, 'vertical' | 'horizontal'>) => {
    const { table, tableStart, rect, anchor, source, steps } = alignmentTarget()
    const projected = editor.schema.nodeFromJSON(projectDocxCellAlignment(source, anchor, [...steps, { ...rect, ...alignment }], editor.schema))
    const tr = closeHistory(editor.state.tr).replaceWith(tableStart - 1, tableStart - 1 + table.nodeSize, projected)
    tr.setSelection(Selection.fromJSON(tr.doc, editor.state.selection.toJSON()))
    editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
  }
  const tableAlignmentTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后调整整表对齐')
    const selection = editor.state.selection
    let table, tableStart: number
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格')
      const rect = selectedRect(editor.state); table = rect.table; tableStart = rect.tableStart
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxTableAlignmentAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.tableAlignmentEditable || !anchor.tableAlignmentSource) throw new Error(anchor?.tableAlignmentReadOnlyReason ?? '当前来源表格不支持整表对齐，请先保存新增表格')
    const intent = table.attrs.nativeTableAlignment as { alignment: DocxTableAlignment } | null
    if (intent && (Object.keys(intent).length !== 1 || !['left', 'center', 'right'].includes(intent.alignment))) throw new Error('整表对齐草稿字段无效')
    if (!equal(table.toJSON(), intent ? projectDocxTableAlignment(source, anchor, intent.alignment, editor.schema) : source)) throw new Error('整表对齐不能与同表文字、格式或其他修改混用，请先保存')
    return { table, tableStart, source, anchor }
  }
  const tableAlignmentDialog = () => {
    const target = tableAlignmentTarget(), frozen = editor.getJSON(), selection = editor.state.selection.toJSON(), capturedAnchor = JSON.stringify(target.anchor)
    const initial: DocxTableAlignment = target.table.attrs.tblAlign === 'center' || target.table.attrs.tblAlign === 'right' ? target.table.attrs.tblAlign : 'left'
    openDocxTableAlignmentDialog(editor.view.dom.ownerDocument.body, initial, target.anchor.tableAlignmentSource!.positioning === 'floating', value => {
      const current = tableAlignmentTarget()
      if (!equal(frozen, editor.getJSON()) || !equal(selection, editor.state.selection.toJSON()) || capturedAnchor !== JSON.stringify(current.anchor)) throw new Error('整表对齐对话框打开后文档、选区或来源已改变，请重新选择')
      if (value === initial) return
      const projected = editor.schema.nodeFromJSON(projectDocxTableAlignment(current.source, current.anchor, value, editor.schema))
      const tr = closeHistory(editor.state.tr).replaceWith(current.tableStart - 1, current.tableStart - 1 + current.table.nodeSize, projected)
      tr.setSelection(Selection.fromJSON(tr.doc, selection))
      editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
    })
  }
  const tableAlignmentReason = () => { try { tableAlignmentTarget(); return null } catch (error) { return error instanceof Error ? error.message : '当前来源表格不支持整表对齐' } }
  const rowBreakTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后调整行跨页')
    const selection = editor.state.selection
    let table, tableStart: number, top: number, bottom: number
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1; top = 0; bottom = table.childCount
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格或逻辑行')
      const rect = selectedRect(editor.state); table = rect.table; tableStart = rect.tableStart; top = rect.top; bottom = rect.bottom
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxRowBreakAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.rowBreakEditable || !anchor.rowBreakSource) throw new Error(anchor?.rowBreakReadOnlyReason ?? '当前来源表格不支持行跨页设置，请先保存新增表格')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表行跨页混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    const intent = table.attrs.nativeTableRowBreaks as { steps: TableRowBreakStep[] } | null, steps = intent?.steps ?? []
    if (intent && (Object.keys(intent).length !== 1 || !Array.isArray(steps) || !steps.length)) throw new Error('行跨页草稿字段无效')
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表行跨页修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxRowBreaks(source, anchor, steps, editor.schema) : source)) throw new Error('行跨页不能与同表文字、格式或其他修改混用，请先保存')
    return { table, tableStart, top, bottom, anchor, source, steps }
  }
  const rowBreakDialog = () => {
    const target = rowBreakTarget(), frozen = editor.getJSON(), selection = editor.state.selection.toJSON(), capturedAnchor = JSON.stringify(target.anchor)
    const values = Array.from({ length: target.bottom - target.top }, (_, index) => !target.table.child(target.top + index).attrs.cantSplit)
    const initial = values.every(value => value === values[0]) ? values[0]! : null
    openDocxRowBreaksDialog(editor.view.dom.ownerDocument.body, initial, target.top, target.bottom, value => {
      const current = rowBreakTarget()
      if (!equal(frozen, editor.getJSON()) || !equal(selection, editor.state.selection.toJSON()) || capturedAnchor !== JSON.stringify(current.anchor)) throw new Error('行跨页对话框打开后文档、选区或来源已改变，请重新选择')
      if (value === undefined) return
      const projected = editor.schema.nodeFromJSON(projectDocxRowBreaks(current.source, current.anchor, [...current.steps, { top: current.top, bottom: current.bottom, allowBreak: value }], editor.schema))
      const tr = closeHistory(editor.state.tr).replaceWith(current.tableStart - 1, current.tableStart - 1 + current.table.nodeSize, projected)
      tr.setSelection(Selection.fromJSON(tr.doc, selection))
      editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
    })
  }
  const rowBreakReason = () => { try { rowBreakTarget(); return null } catch (error) { return error instanceof Error ? error.message : '当前来源表格不支持行跨页设置' } }
  const altTextTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层单元格内定位后修改标题/说明')
    const selection = editor.state.selection
    if (selection instanceof NodeSelection) throw new Error('请先进入表格单元格后修改标题/说明')
    if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格')
    const rect = selectedRect(editor.state), table = rect.table, tableStart = rect.tableStart
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxTableAltTextAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.tableAltTextEditable || !anchor.tableAltTextSource) throw new Error(anchor?.tableAltTextReadOnlyReason ?? '当前来源表格不支持标题/说明，请先保存新增表格')
    const intent = table.attrs.nativeTableAltText
    if (!equal(table.toJSON(), intent ? projectDocxTableAltText(source, anchor, normalizeTableAltText(intent), editor.schema) : source)) throw new Error('标题/说明不能与同表文字、格式或其他修改混用，请先保存')
    return { table, tableStart, source, anchor }
  }
  const altTextDialog = () => {
    const target = altTextTarget(), frozen = editor.getJSON(), selection = editor.state.selection.toJSON(), capturedAnchor = JSON.stringify(target.anchor)
    const initial = {title: target.table.attrs.tblCaption ?? '', description: target.table.attrs.tblDescription ?? ''}
    openDocxTableAltTextDialog(editor.view.dom.ownerDocument.body, initial, value => {
      const current = altTextTarget()
      if (!equal(frozen, editor.getJSON()) || !equal(selection, editor.state.selection.toJSON()) || capturedAnchor !== JSON.stringify(current.anchor)) throw new Error('标题/说明对话框打开后文档、选区或来源已改变，请重新选择')
      if (equal(value, initial)) return
      const projected = editor.schema.nodeFromJSON(projectDocxTableAltText(current.source, current.anchor, value, editor.schema))
      const tr = closeHistory(editor.state.tr).replaceWith(current.tableStart - 1, current.tableStart - 1 + current.table.nodeSize, projected)
      tr.setSelection(Selection.fromJSON(tr.doc, selection)); editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
    })
  }
  const altTextReason = () => { try { altTextTarget(); return null } catch(error) { return error instanceof Error ? error.message : '当前来源不支持标题/说明' } }
  const altTextNavigation = () => attachDocxTableAltTextNavigation(editor.view.dom.ownerDocument, altTextReason(), altTextDialog)
  const wrapTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层单元格内定位后调整自动换行')
    const selection = editor.state.selection
    let table, tableStart: number, rect: { top: number; left: number; bottom: number; right: number }
    if (selection instanceof NodeSelection) throw new Error('请先在单元格内定位或选择完整矩形单元格')
    {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的完整矩形单元格')
      const selected = selectedRect(editor.state); table = selected.table; tableStart = selected.tableStart
      rect = { top: selected.top, left: selected.left, bottom: selected.bottom, right: selected.right }
    }
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxCellWrapAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.tableCellWrapEditable || !anchor.tableCellWrapSource) throw new Error(anchor?.tableCellWrapReadOnlyReason ?? '当前来源表格不支持自动换行，请先保存新增表格')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表自动换行混用，请先保存')
    const intent = table.attrs.nativeTableCellWrap as { steps: TableCellWrapStep[] } | null
    const steps = intent?.steps ?? []
    if (intent && (Object.keys(intent).length !== 1 || !Array.isArray(steps) || !steps.length)) throw new Error('自动换行草稿字段无效')
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表自动换行修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxCellWrap(source, anchor, steps, editor.schema) : source)) throw new Error('自动换行不能与同表文字、格式或其他修改混用，请先保存')
    const map = TableMap.get(table)
    const selected = anchor.tableCellWrapSource.cells.filter(cell => cell.top < rect.bottom && cell.bottom > rect.top && cell.left < rect.right && cell.right > rect.left)
    if (!selected.length || selected.some(cell => cell.top < rect.top || cell.bottom > rect.bottom || cell.left < rect.left || cell.right > rect.right)) throw new Error('请选择包含完整合并单元格的矩形范围')
    const values = selected.map(cell => !table.nodeAt(map.map[cell.top * map.width + cell.left]!)!.attrs.noWrap)
    return { table, tableStart, rect, source, anchor, steps, values }
  }
  const wrapDialog = () => {
    const target = wrapTarget(), frozen = editor.getJSON(), selection = editor.state.selection.toJSON(), capturedAnchor = JSON.stringify(target.anchor)
    const initial = target.values.every(value => value === target.values[0]) ? target.values[0]! : null
    openDocxCellWrapDialog(editor.view.dom.ownerDocument.body, initial, value => {
      const current = wrapTarget()
      if (!equal(frozen, editor.getJSON()) || !equal(selection, editor.state.selection.toJSON()) || capturedAnchor !== JSON.stringify(current.anchor)) throw new Error('自动换行对话框打开后文档、选区或来源已改变，请重新选择')
      if (value === undefined || current.values.every(v => v === value)) return
      const projected = editor.schema.nodeFromJSON(projectDocxCellWrap(current.source, current.anchor, [...current.steps, { ...current.rect, wrap: value }], editor.schema))
      const tr = closeHistory(editor.state.tr).replaceWith(current.tableStart - 1, current.tableStart - 1 + current.table.nodeSize, projected)
      tr.setSelection(Selection.fromJSON(tr.doc, selection)); editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
    })
  }
  const wrapReason = () => { try { wrapTarget(); return null } catch(error) { return error instanceof Error ? error.message : '当前来源不支持自动换行' } }
  const wrapNavigation = () => attachDocxCellWrapNavigation(editor.view.dom.ownerDocument, wrapReason(), wrapDialog)
  const marginOverridesTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层单元格内定位后调整边距')
    const selection = editor.state.selection
    let table, tableStart: number, rect: { top: number; left: number; bottom: number; right: number }
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1
      rect = { top: 0, left: 0, bottom: table.childCount, right: TableMap.get(table).width }
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的完整矩形单元格')
      const selected = selectedRect(editor.state); table = selected.table; tableStart = selected.tableStart
      rect = { top: selected.top, left: selected.left, bottom: selected.bottom, right: selected.right }
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxCellMarginOverridesAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.tableCellMarginOverridesEditable || !anchor.tableCellMarginOverridesSource) throw new Error(anchor?.tableCellMarginOverridesReadOnlyReason ?? '当前来源表格不支持单元格边距，请先保存新增表格')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表单元格边距混用，请先保存')
    const intent = table.attrs.nativeTableCellMarginOverrides as { steps: TableCellMarginOverrideStep[] } | null
    const steps = intent?.steps ?? []
    if (intent && (Object.keys(intent).length !== 1 || !Array.isArray(steps) || !steps.length)) throw new Error('单元格边距草稿字段无效')
    if (steps.length >= MAX_TABLE_STEPS) throw new Error('此表单元格边距修改步骤过多，请先保存')
    if (!equal(table.toJSON(), steps.length ? projectDocxCellMarginOverrides(source, anchor, steps, editor.schema) : source)) throw new Error('单元格边距不能与同表文字、格式或其他修改混用，请先保存')
    const map = TableMap.get(table)
    const state = steps.length ? replayTableCellMarginOverrides(anchor.tableCellMarginOverridesSource, steps) : null
    const selected = anchor.tableCellMarginOverridesSource.cells.map((cell, index) => ({ ...cell, index })).filter(cell => cell.top < rect.bottom && cell.bottom > rect.top && cell.left < rect.right && cell.right > rect.left)
    if (!selected.length || selected.some(cell => cell.top < rect.top || cell.bottom > rect.bottom || cell.left < rect.left || cell.right > rect.right)) throw new Error('请选择包含完整合并单元格的矩形范围')
    const cells = selected.map(cell => {
      const hasPhysicalOverrides = state ? state.hasPhysicalOverrides[cell.index]! : cell.hasPhysicalOverrides
      const rawPresent = state ? state.rawPresent[cell.index]! : cell.rawPresent
      const raw = state ? state.raw[cell.index]! : cell.raw
      const node = table.nodeAt(map.map[cell.top * map.width + cell.left]!)!
      const effective = node.attrs.cellMar as Partial<{ top: number; right: number; bottom: number; left: number }> | null
      return { rawPresent, raw, effective, hasPhysicalOverrides }
    })
    return { table, tableStart, rect, source, anchor, steps, cells }
  }
  const marginOverridesDialog = () => {
    const target = marginOverridesTarget(), frozen = editor.getJSON(), selection = editor.state.selection.toJSON(), capturedAnchor = JSON.stringify(target.anchor)
    const sides = ['top', 'right', 'bottom', 'left'] as const
    const defaults = target.table.attrs.cellMar as Partial<{ top: number; right: number; bottom: number; left: number }> | null
    const initial = Object.fromEntries(sides.map(side => {
      const values = target.cells.map(cell => cell.effective?.[side] ?? defaults?.[side] ?? (side === 'left' || side === 'right' ? 108 : 0))
      return [side, values.every(value => value === values[0]) ? values[0]! : null]
    })) as Record<typeof sides[number], number | null>
    const count = target.cells.filter(cell => cell.rawPresent).length
    const coverage = count === 0 ? '所选单元格使用继承边距' : count === target.cells.length ? '所选单元格含自定义边距' : '所选单元格同时包含自定义与继承边距'
    openDocxCellMarginOverridesDialog(editor.view.dom.ownerDocument.body, initial, coverage, value => {
      const current = marginOverridesTarget()
      if (!equal(frozen, editor.getJSON()) || !equal(selection, editor.state.selection.toJSON()) || capturedAnchor !== JSON.stringify(current.anchor)) throw new Error('单元格边距对话框打开后文档、选区或来源已改变，请重新选择')
      if (value === undefined || value === null && current.cells.every(cell => !cell.hasPhysicalOverrides)) return
      if (value && current.cells.every(cell => cell.rawPresent && sides.every(side => cell.raw?.[side] === value[side]))) return
      const projected = editor.schema.nodeFromJSON(projectDocxCellMarginOverrides(current.source, current.anchor, [...current.steps, { ...current.rect, margins: value }], editor.schema))
      const tr = closeHistory(editor.state.tr).replaceWith(current.tableStart - 1, current.tableStart - 1 + current.table.nodeSize, projected)
      tr.setSelection(Selection.fromJSON(tr.doc, selection))
      editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
    }, { reason: rowBreakReason(), open: rowBreakDialog }, { reason: tableAlignmentReason(), open: tableAlignmentDialog })
  }
  const propertiesTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('请先在外层表格内定位')
    const selection=editor.state.selection
    const table=selection instanceof NodeSelection&&selection.node.type.name==='docTable'?selection.node:selectedRect(editor.state).table
    const tableStart=selection instanceof NodeSelection?selection.from+1:selectedRect(editor.state).tableStart
    const index=table.attrs.docxIndex,anchor=anchors.find(a=>a.docxIndex===index)
    const source=baseline.content?.find(n=>n.type==='docTable'&&n.attrs?.docxIndex===index)
    if(!anchor?.tablePropertiesEditable||!source)throw new Error(anchor?.tablePropertiesReadOnlyReason??'当前来源不支持完整表格属性')
    const expected=table.attrs.nativeTableProperties?projectDocxTableProperties(source,anchor,table.attrs.nativeTableProperties,editor.schema):source
    if(!equal(expected,table.toJSON()))throw new Error('完整表格属性不能与同表文字、格式或其他修改混用，请先保存')
    return{table,tableStart,anchor,source}
  }
  const propertiesReason = () => {try{propertiesTarget();return null}catch(error){return error instanceof Error?error.message:'当前表格属性不可编辑'}}
  const propertiesDialog = () => {
    let target=propertiesTarget()
    if(editor.state.selection instanceof NodeSelection){const map=TableMap.get(target.table);editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,target.tableStart+map.map[0],target.tableStart+map.map[map.map.length-1])))}
    let frozen=JSON.stringify(editor.getJSON()),capturedAnchor=JSON.stringify(target.anchor),selection=JSON.stringify(editor.state.selection.toJSON())
    openDocxTablePropertiesSourceDialog(editor,(target.anchor.columnWidthMaxTwips??9360)/15,command=>{
      target=propertiesTarget()
      if(frozen!==JSON.stringify(editor.getJSON())||capturedAnchor!==JSON.stringify(target.anchor)||selection!==JSON.stringify(editor.state.selection.toJSON()))throw new Error('对话框打开后文档、选区或来源已改变，请重新选择')
      command(editor.state,tr=>{
        const next=tr.doc.nodeAt(target.tableStart-1)
        if(!next||next.type.name!=='docTable')throw new Error('表格来源已改变')
        const patch=tablePropertiesPatchOf(target.source,next.toJSON(),editor.schema)
        const projected=patch?editor.schema.nodeFromJSON(projectDocxTableProperties(target.source,target.anchor,patch,editor.schema)):editor.schema.nodeFromJSON(target.source)
        if(!equal(next.toJSON(),target.table.toJSON()))tr.replaceWith(target.tableStart-1,target.tableStart-1+next.nodeSize,projected)
        editor.view.dispatch(tr)
        frozen=JSON.stringify(editor.getJSON());selection=JSON.stringify(editor.state.selection.toJSON())
      })
    })
  }
  const marginsTarget = () => {
    if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (nestedInputActive()) throw new Error('嵌套表格当前支持文字编辑，请先在外层表格内定位后调整默认边距')
    const selection = editor.state.selection
    let table, tableStart: number
    if (selection instanceof NodeSelection) {
      if (selection.node.type.name !== 'docTable') throw new Error('请先选择表格或在单元格内定位')
      table = selection.node; tableStart = selection.from + 1
    } else {
      if (!(selection instanceof CellSelection) && cellAround(selection.$from)?.pos !== cellAround(selection.$to)?.pos) throw new Error('请选择同一表格的单元格')
      const selected = selectedRect(editor.state); table = selected.table; tableStart = selected.tableStart
    }
    if (table.attrs.nativeTableCellWrap) throw new Error('自动换行修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableAltText) throw new Error('标题/说明修改后不能与同表其他修改混用，请先保存')
    const index = table.attrs.docxIndex, anchor = anchors.find(item => item.docxIndex === index) as (DocxAnchor & DocxCellMarginsAnchor) | undefined
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === index)
    if (!source || !anchor?.tableCellMarginsEditable) throw new Error(anchor?.tableCellMarginsReadOnlyReason ?? '当前来源表格不支持默认边距，请先保存新增表格')
    if (table.attrs.nativeTableAlignment) throw new Error('整表对齐修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableStyle) throw new Error('表格样式修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableRowBreaks) throw new Error('行跨页修改后不能与同表其他修改混用，请先保存')
    if (table.attrs.nativeTableCellMarginOverrides) throw new Error('单元格边距修改后不能与同表默认边距混用，请先保存')
    const intent = table.attrs.nativeTableCellMargins as { margins: { top: number; right: number; bottom: number; left: number } } | null
    if (!equal(table.toJSON(), intent ? projectDocxCellMargins(source, anchor, intent.margins, editor.schema) : source)) throw new Error('默认边距不能与同表文字、格式或其他结构修改混用，请先保存')
    return { table, tableStart, anchor, source }
  }
  const marginsDialog = () => {
    const target = marginsTarget(), frozen = editor.getJSON(), selection = editor.state.selection.toJSON(), capturedAnchor = JSON.stringify(target.anchor)
    const defaults = target.table.attrs.cellMar as Partial<{ top: number; right: number; bottom: number; left: number }> | null
    const margins = { top: defaults?.top ?? 0, right: defaults?.right ?? 108, bottom: defaults?.bottom ?? 0, left: defaults?.left ?? 108 }
    openDocxCellMarginsDialog(editor.view.dom.ownerDocument.body, margins, Object.keys(margins).filter(side => defaults?.[side as keyof typeof margins] == null), value => {
      const current = marginsTarget()
      if (!equal(frozen, editor.getJSON()) || !equal(selection, editor.state.selection.toJSON()) || capturedAnchor !== JSON.stringify(current.anchor)) throw new Error('默认边距对话框打开后文档、选区或来源已改变，请重新选择')
      if (equal(value, margins)) return
      const projected = editor.schema.nodeFromJSON(projectDocxCellMargins(current.source, current.anchor, value, editor.schema))
      const tr = closeHistory(editor.state.tr).replaceWith(current.tableStart - 1, current.tableStart - 1 + current.table.nodeSize, projected)
      tr.setSelection(Selection.fromJSON(tr.doc, selection))
      editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.commands.focus()
    })
  }
  const isWidth = (action: string) => action === 'table-column-width' || action === 'table-distribute-columns'
  const isShape = (action: string) => action === 'table-merge-cells' || action === 'table-split-cells'
  const styleCommands: DocxTableCommands = {
    active: action => docxTableStyleActive(editor, baseline, anchors, action),
    reason: action => nestedInputActive() ? '嵌套表格当前支持文字编辑，请先在外层表格内定位后修改表格样式' : docxTableStyleUnavailable(editor, baseline, anchors, action),
    run(action) {
      try {
        if (action !== 'table-style-custom') { applyDocxTableStyle(editor, baseline, anchors, action); return }
        const reason = styleCommands.reason(action)
        if (reason) throw new Error(reason)
        const gallery = docxTableStyleOptionsAt(editor, baseline, anchors)
        openDocxTableStyleGallery(editor.view.dom.ownerDocument.body, gallery.options, gallery.styleId, styleId => {
          try { applyDocxTableStyle(editor, baseline, anchors, action, styleId) } catch (error) { reportError(error) }
        })
      } catch (error) { reportError(error) }
    },
  }
  const commands: DocxTableCommands = {
    active(action) { if (isDocxTableStyleAction(action)) return styleCommands.active!(action); try { if (alignmentActions[action]) return alignmentActive(alignmentActions[action]); if (directionActions[action]) return directionActive(directionActions[action]); if (autoFitModes[action]) return autoFitTarget().table.attrs.tblAutoFit === autoFitModes[action]; return action==='table-repeat-header-rows' && headerTarget().active } catch { return false } },
    reason(action) { if (isDocxTableStyleAction(action)) return styleCommands.reason(action); try { if(TABLE_SELECTION_ACTIONS[action])selectionTarget();else if(action==='table-properties'){const reason=propertiesReason();if(reason)throw new Error(reason)}else if(action==='table-alt-text')altTextTarget();else if(action==='table-cell-wrap')wrapTarget();else if(action==='table-row-breaks')rowBreakTarget();else if(action==='table-alignment')tableAlignmentTarget();else if(action==='table-cell-margins')marginsTarget();else if(alignmentActions[action])alignmentTarget();else if(directionActions[action])directionTarget();else if(autoFitModes[action])autoFitTarget();else if(action==='table-row-height'||action==='table-distribute-rows')heightTarget();else if(isWidth(action))widthTarget();else if(isShape(action))shapeTarget(action);else if(action==='table-repeat-header-rows')headerTarget();else target(action); return null } catch (error) { return error instanceof Error && !/No cell|Not in a table/.test(error.message) ? error.message : '请先在表格单元格内定位' } },
    run(action) {
      if (isDocxTableStyleAction(action)) { styleCommands.run(action); return }
      try {
        if(action!=='table-properties'&&!TABLE_SELECTION_ACTIONS[action]) { try { const rect=selectedRect(editor.state);if(rect.table.attrs.nativeTableProperties)throw new Error('完整表格属性修改后请先保存') } catch(error) { if(error instanceof Error&&error.message.includes('完整表格属性'))throw error } }
        if (TABLE_SELECTION_ACTIONS[action]) { selectTablePart(action); return }
        if (action === 'table-cell-wrap') { wrapDialog(); return }
        if (action === 'table-properties') { propertiesDialog(); return }
        if (action === 'table-alt-text') { altTextDialog(); return }
        if (action === 'table-alignment') { tableAlignmentDialog(); return }
        if (action === 'table-row-breaks') { rowBreakDialog(); return }
        if (action === 'table-cell-margins') { marginsDialog(); return }
        if (alignmentActions[action]) { applyAlignment(alignmentActions[action]); return }
        if (directionActions[action]) { applyDirection(directionActions[action]); return }
        if (autoFitModes[action]) { applyAutoFit(autoFitModes[action]); return }
        if (action === 'table-distribute-rows') { void distributeHeight().catch(reportError); return }
        if (action === 'table-row-height') {
          const target = heightTarget(), frozen = { doc: editor.getJSON(), selection: editor.state.selection.toJSON() }
          openDocxRowHeightDialog(editor.view.dom.ownerDocument.body, target.table.child(target.top).attrs.heightTwips ?? null, target.anchor.rowHeightMaxTwips!, height => applyHeight(height, frozen))
          return
        }
        if (isWidth(action)) {
          const target = widthTarget()
          if (action === 'table-distribute-columns') applyWidth()
          else {
            const frozen = { doc: editor.getJSON(), selection: editor.state.selection.toJSON() }
            const first = TableMap.get(target.table).map[target.left]!, rect = TableMap.get(target.table).findCell(first)
            const initial = Math.round((target.table.nodeAt(first)!.attrs.colwidth?.[target.left - rect.left] ?? target.anchor.columnWidthsTwips![target.left]! / 15) * 15)
            openDocxColumnWidthDialog(editor.view.dom.ownerDocument.body, initial, width => applyWidth(width, frozen))
          }
          return
        }
        if (isShape(action)) {
          shapeTarget(action)
          if (action === 'table-merge-cells') applyShape(action)
          else { const before = editor.getJSON(); openDocxCellSplitDialog(editor.view.dom.ownerDocument.body, options => applyShape(action, options, before)) }
          return
        }
        if(action==='table-repeat-header-rows'){
          const {rect,active}=headerTarget();let tr=closeHistory(editor.state.tr)
          rect.table.forEach((row,offset,index)=>{if(index<rect.bottom)tr=tr.setNodeMarkup(rect.tableStart+offset,undefined,{...row.attrs,repeatHeader:!active,repeatHeaderEdited:true})})
          editor.view.dispatch(tr);editor.view.dispatch(closeHistory(editor.state.tr));editor.commands.focus();return
        }
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
  return commands
}
