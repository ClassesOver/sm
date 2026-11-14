import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { normalizeDocxParagraphProperties } from '../../../reporting/doc_engine/bridge/docx-paragraph-properties'
import { projectDocxParagraphProperties } from './docx-paragraph-properties'

export interface DocxTableCellParagraphPropertiesIntent {
  cellId: string
  paragraphIndex: number
  values: Record<string, unknown>
}

const otherTableIntents = ['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableRowBreaks','nativeTableCellMarginOverrides','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableCellTextDirection','nativeTableCellMargins','nativeTableCellAlignment']

export function projectDocxTableCellParagraphProperties(source: DocxPmNode, anchor: DocxAnchor, row: number, column: number, paragraphIndex: number, input: unknown, schema?: Schema): DocxPmNode {
  if (!schema || source.type !== 'docTable' || !Number.isInteger(row) || !Number.isInteger(column) || !Number.isInteger(paragraphIndex)) throw new Error('表格段落属性目标无效')
  if (otherTableIntents.some(key => source.attrs?.[key])) throw new Error('表格段落设置不能与同表其他修改混合，请先保存')
  const cellAnchor = anchor.cells?.[row]?.[column], cell = source.content?.[row]?.content?.[column]
  const paragraphIdentity = cellAnchor?.paragraphs?.find(item => item.index === paragraphIndex)
  const paragraph = cell?.content?.[paragraphIndex]
  if (!cellAnchor?.editable || !paragraphIdentity?.editable || !paragraph || !['docParagraph','docHeading','docListItem'].includes(paragraph.type)) throw new Error('此单元格段落来源暂不支持设置')
  const values = normalizeDocxParagraphProperties(input)
  const paragraphAnchor: DocxAnchor = { ...anchor, editable: true, paragraphPropertiesEditable: true, paragraphLayoutEditable: true }
  const result = structuredClone(source)
  result.content![row]!.content![column]!.content![paragraphIndex] = projectDocxParagraphProperties(paragraph, paragraphAnchor, values, schema)
  result.attrs = { ...result.attrs, nativeTableCellParagraphProperties: { cellId: cellAnchor.cellId, expectedCellSha256: cellAnchor.expectedObjectSha256, paragraphIndex, expectedParagraphSha256: paragraphIdentity.expectedObjectSha256, values } }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}

export function docxTableCellParagraphPropertiesOperation(source: DocxPmNode, edited: DocxPmNode, anchor: DocxAnchor, schema?: Schema) {
  const intent = edited.attrs?.nativeTableCellParagraphProperties as (DocxTableCellParagraphPropertiesIntent & { expectedCellSha256?: string; expectedParagraphSha256?: string }) | undefined
  if (!intent || !schema || Object.keys(intent).some(key => !['cellId','expectedCellSha256','paragraphIndex','expectedParagraphSha256','values'].includes(key))) throw new Error('表格段落设置意图无效')
  const position = anchor.cells?.flatMap((cells, r) => cells.map((cell, c) => ({ ...cell, r, c }))).find(cell => cell.cellId === intent.cellId)
  if (!position) throw new Error('表格段落设置来源身份无效')
  const projected = projectDocxTableCellParagraphProperties(source, anchor, position.r, position.c, intent.paragraphIndex, intent.values, schema)
  if (!sameDocxJson(projected, edited)) throw new Error('表格段落设置不能与同表正文或其他格式混改，请先保存')
  return { kind: 'setTableCellParagraphProperties', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, cellId: position.cellId,
    expectedCellSha256: position.expectedObjectSha256, paragraphIndex: intent.paragraphIndex, expectedParagraphSha256: intent.expectedParagraphSha256, values: normalizeDocxParagraphProperties(intent.values) }
}

function sameDocxJson(left: unknown, right: unknown) { return JSON.stringify(left) === JSON.stringify(right) }
