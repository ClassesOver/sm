import type { Editor } from '@tiptap/core'
import type { Schema } from '@tiptap/pm/model'
import { TextSelection } from '@tiptap/pm/state'
import { tableModelToPmNode } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { wordTableCell, wordTableModel } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/new-table'
import type { DocxPmNode } from './docx-operations'

/**
 * Insert ▸ Table, following GenOffice f8c17004 components/ribbon-tabs.tsx
 * insertTableAt and editor/new-table.ts (vendored unmodified): a full-width
 * autofit grid of equal columns with Word's single 0.5pt borders and
 * vertically centred, single-spaced cell paragraphs.
 *
 * Local save boundary: the editor node carries `nativeTableInsert` {rows, cols}
 * and must equal the deterministic projection of that size; the native diff
 * turns it into an `insertTable` operation the bridge writes with the engine's
 * generateTableModelXml. Plain text typed into the new cells before saving is
 * carried as `cells` (the projection is recomputed with those texts and must
 * still match); marks, cell/paragraph formatting or layout changes are refused
 * until the table is saved and becomes a source table. Size follows the existing table structure
 * budget (≤100 rows, ≤30 columns, ≤1000 cells), stricter than the source
 * picker caps (200×63).
 */
export const NEW_TABLE_LIMITS = { rows: 100, cols: 30, cells: 1000 } as const
export const DOCX_TABLE_NESTED = '表格或嵌套内容中暂不能插入表格；请将光标放在正文段落'

export function newTableSize(value: unknown): { rows: number; cols: number } {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !['rows', 'cols'].includes(key))) throw new Error('新增表格字段无效')
  const { rows, cols } = value as { rows: unknown; cols: unknown }
  if (!Number.isInteger(rows) || !Number.isInteger(cols) || (rows as number) < 1 || (cols as number) < 1
    || (rows as number) > NEW_TABLE_LIMITS.rows || (cols as number) > NEW_TABLE_LIMITS.cols
    || (rows as number) * (cols as number) > NEW_TABLE_LIMITS.cells) throw new Error(`新增表格须在 ${NEW_TABLE_LIMITS.rows} 行、${NEW_TABLE_LIMITS.cols} 列、${NEW_TABLE_LIMITS.cells} 个单元格以内`)
  return { rows: rows as number, cols: cols as number }
}

/** Plain cell texts of a new table: rows×cols strings, '\n' separates cell
 *  paragraphs (the replaceCellText convention); same control-character and
 *  size limits as paragraph text. */
export function newTableCells(value: unknown, rows: number, cols: number): string[][] {
  if (!Array.isArray(value) || value.length !== rows || value.some(row => !Array.isArray(row) || row.length !== cols)) throw new Error('新增表格单元格与行列数不一致')
  let total = 0
  for (const row of value as unknown[][]) for (const text of row) {
    if (typeof text !== 'string' || text.length > 20000 || /[\x00-\x08\x0b-\x1f]/.test(text)) throw new Error('新增表格单元格文字无效')
    total += text.length
  }
  if (total > 200000) throw new Error('新增表格文字超出预算')
  return value as string[][]
}

/** Deterministic editor projection of a fresh rows×cols table (fixed-source
 *  model), optionally with plain cell texts typed before the first save. */
export function projectNewDocxTable(value: unknown, schema: Schema, cells?: string[][]): DocxPmNode {
  const { rows, cols } = newTableSize(value)
  const texts = cells === undefined ? undefined : newTableCells(cells, rows, cols)
  const model = wordTableModel(Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => wordTableCell((texts?.[r]![c] ?? '').split('\n')))), cols)
  const node = schema.nodeFromJSON(tableModelToPmNode(model)).toJSON() as DocxPmNode
  node.attrs = { ...node.attrs, nativeTableInsert: { rows, cols } }
  return schema.nodeFromJSON(node).toJSON() as DocxPmNode
}

const textOfCellParagraph = (node: DocxPmNode): string => (node.content ?? []).map(child => child.type === 'text' ? child.text ?? '' : '\uFFFC').join('')
/** Cell texts read back from a new table node (shape checked by the projection compare). */
export function newTableNodeCells(node: DocxPmNode): string[][] {
  return (node.content ?? []).map(row => (row.content ?? []).map(cell => (cell.content ?? []).map(textOfCellParagraph).join('\n')))
}

/** `originalFormatting` is a run-formatting snapshot the vendored projection
 *  derives at creation time (it still describes the empty cells after typing);
 *  it is not document content and the bridge rebuilds the table from
 *  rows/cols/cells, so the projection compare ignores it. Everything else —
 *  rows, cells, paragraphs, marks and attributes — must match exactly. */
export function newTableMatchesProjection(node: DocxPmNode, expected: DocxPmNode): boolean {
  const strip = (value: DocxPmNode) => JSON.stringify({ ...value, attrs: { ...value.attrs, originalFormatting: null } })
  return strip(node) === strip(expected)
}

export function docxTableInsertUnavailable(editor: Editor, editable: boolean): string | undefined {
  if (!editable || !editor.isEditable) return '当前文档不可编辑或正在保存'
  const { $from } = editor.state.selection
  if ($from.depth !== 1 || !$from.parent.isTextblock || !editor.schema.nodes.docTable) return DOCX_TABLE_NESTED
  return undefined
}

/**
 * Source placement: an empty caret paragraph stays below the new table; a
 * caret mid-paragraph splits it around the table; at a paragraph start the
 * table goes before it and at its end after it. A table never touches another
 * table or the document end — an empty paragraph is kept/added between, as
 * Word requires. The split half clears docxIndex (same rule as page breaks).
 * One dispatch, caret in the first cell.
 */
export function insertDocxTable(editor: Editor, rows: number, cols: number): boolean {
  const reason = docxTableInsertUnavailable(editor, true)
  if (reason) throw new Error(reason)
  const schema = editor.state.schema
  const tableNode = schema.nodeFromJSON(projectNewDocxTable({ rows, cols }, schema))
  const emptyParagraph = () => schema.nodes.docParagraph!.create()
  const tr = editor.state.tr
  if (!tr.selection.empty) tr.deleteSelection()
  const $from = tr.selection.$from
  if ($from.depth !== 1 || !$from.parent.isTextblock) throw new Error(DOCX_TABLE_NESTED)
  const paragraph = $from.parent
  let at: number
  if (paragraph.content.size === 0 || $from.parentOffset === 0) at = $from.before(1)
  else if ($from.parentOffset === paragraph.content.size) at = $from.after(1)
  else {
    tr.split($from.pos, 1, [{ type: paragraph.type, attrs: { ...paragraph.attrs, docxIndex: null } }])
    at = tr.doc.resolve(tr.mapping.map($from.pos)).before(1)
  }
  const before = tr.doc.resolve(at).nodeBefore
  if (before?.type.name === 'docTable') { tr.insert(at, emptyParagraph()); at += 2 }
  tr.insert(at, tableNode)
  const afterTable = at + tableNode.nodeSize
  const next = tr.doc.resolve(afterTable).nodeAfter
  if (!next || !next.isTextblock) tr.insert(afterTable, emptyParagraph())
  tr.setSelection(TextSelection.near(tr.doc.resolve(at + 1)))
  const previous = editor.state.doc
  editor.view.dispatch(tr.scrollIntoView())
  // 原生保存守卫（docx-main filterTransaction）拒绝时文档不变：如实报告而不是静默无效。
  if (editor.state.doc === previous) throw new Error('表格未插入：此位置的拆分段落带有暂不支持保存的样式或格式，请先保存或换到普通段落')
  editor.view.focus()
  return true
}
