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
  if (!schema || !anchor.editable || source.type !== 'docTable' || !Number.isInteger(row) || !Number.isInteger(column) || !Number.isInteger(paragraphIndex)) throw new Error('表格段落属性目标无效')
  if (otherTableIntents.some(key => source.attrs?.[key])) throw new Error('表格段落设置不能与同表其他修改混合，请先保存')
  const cellAnchor = anchor.cells?.[row]?.[column], cell = source.content?.[row]?.content?.[column]
  const paragraphIdentity = cellAnchor?.paragraphs?.find(item => item.index === paragraphIndex)
  const paragraph = cell?.content?.[paragraphIndex]
  if (!cellAnchor?.editable || !paragraphIdentity?.editable || !paragraph || !['docParagraph','docHeading','docListItem'].includes(paragraph.type)) throw new Error('此单元格段落来源暂不支持设置')
  const values = normalizeDocxParagraphProperties(input)
  const paragraphAnchor: DocxAnchor = { ...anchor, editable: true, paragraphPropertiesEditable: true, paragraphLayoutEditable: true }
  const result = structuredClone(source)
  result.content![row]!.content![column]!.content![paragraphIndex] = projectDocxParagraphProperties(paragraph, paragraphAnchor, values, schema)
  const previous = source.attrs?.nativeTableCellParagraphProperties as any
  const prior = previous?.targets ?? (previous ? [previous] : [])
  const intent = { cellId: cellAnchor.cellId, expectedCellSha256: cellAnchor.expectedObjectSha256, paragraphIndex, expectedParagraphSha256: paragraphIdentity.expectedObjectSha256, values }
  const targets = [...prior.filter((item: any) => !(item.cellId === intent.cellId && item.paragraphIndex === paragraphIndex)), intent]
  result.attrs = { ...result.attrs, nativeTableCellParagraphProperties: targets.length === 1 ? intent : { targets } }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}

export function docxTableCellParagraphPropertiesOperations(source: DocxPmNode, edited: DocxPmNode, anchor: DocxAnchor, schema?: Schema) {
  const raw = edited.attrs?.nativeTableCellParagraphProperties as any
  if (!raw || !schema || raw.targets && Object.keys(raw).some(key => key !== 'targets')) throw new Error('表格段落设置意图无效')
  const intents = raw.targets ?? [raw]
  if (!Array.isArray(intents) || !intents.length || intents.some((item: any, index: number) => item?.cellId !== intents[0]?.cellId || item?.paragraphIndex !== intents[0]?.paragraphIndex + index)) throw new Error('表格段落设置意图无效')
  const seen = new Set<string>()
  let projected = source
  const operations = intents.map((intent: any) => {
    if (!intent || Object.keys(intent).some(key => !['cellId','expectedCellSha256','paragraphIndex','expectedParagraphSha256','values'].includes(key))) throw new Error('表格段落设置意图无效')
    const position = anchor.cells?.flatMap((cells, r) => cells.map((cell, c) => ({ ...cell, r, c }))).find(cell => cell.cellId === intent.cellId)
    const identity = position?.paragraphs?.find(item => item.index === intent.paragraphIndex)
    const key = `${intent.cellId}:${intent.paragraphIndex}`
    if (!position || !identity || intent.expectedCellSha256 !== position.expectedObjectSha256 || intent.expectedParagraphSha256 !== identity.expectedObjectSha256 || seen.has(key)) throw new Error('表格段落设置来源身份无效')
    seen.add(key)
    projected = projectDocxTableCellParagraphProperties(projected, anchor, position.r, position.c, intent.paragraphIndex, intent.values, schema)
    return { kind: 'setTableCellParagraphProperties', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, cellId: position.cellId,
      expectedCellSha256: position.expectedObjectSha256, paragraphIndex: intent.paragraphIndex, expectedParagraphSha256: identity.expectedObjectSha256, values: normalizeDocxParagraphProperties(intent.values) }
  })
  if (!sameDocxJson(projected, edited)) throw new Error('表格段落设置不能与同表正文或其他格式混改，请先保存')
  return operations
}
export function docxTableCellParagraphPropertiesOperation(source: DocxPmNode, edited: DocxPmNode, anchor: DocxAnchor, schema?: Schema) {
  const operations = docxTableCellParagraphPropertiesOperations(source, edited, anchor, schema)
  if (operations.length !== 1) throw new Error('表格段落设置目标数量无效')
  return operations[0]!
}

function sameDocxJson(left: unknown, right: unknown) { return JSON.stringify(left) === JSON.stringify(right) }
