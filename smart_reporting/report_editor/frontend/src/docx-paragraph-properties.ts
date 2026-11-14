import { Extension } from '@tiptap/core'
import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { normalizeDocxParagraphProperties } from '../../../reporting/doc_engine/bridge/docx-paragraph-properties'
import { docxLineSpacingPatch } from '../../../reporting/doc_engine/bridge/docx-line-spacing'

export const NativeDocxParagraphProperties = Extension.create({
  name: 'nativeDocxParagraphProperties',
  addGlobalAttributes: () => [{ types: ['docParagraph', 'docHeading', 'docListItem'], attributes: { nativeParagraphProperties: { default: null, rendered: false } } }],
})
export function projectDocxParagraphProperties(source: DocxPmNode, anchor: DocxAnchor, input: unknown, schema: Schema): DocxPmNode {
  if (!anchor.editable || anchor.paragraphPropertiesEditable === false || anchor.paragraphLayoutEditable === false || !['docParagraph', 'docHeading', 'docListItem'].includes(source.type)) throw new Error('段落来源或可写范围无效')
  const values = normalizeDocxParagraphProperties(input)
  if ('outlineLevel' in values && (source.type === 'docListItem' || source.type === 'docHeading' && source.attrs?.outlineOnly !== true)) throw new Error('列表或样式标题的大纲级别由来源定义')
  const result = structuredClone(source), previous = source.attrs?.nativeParagraphProperties
  result.attrs = { ...result.attrs, ...values, ...docxLineSpacingPatch(values), nativeParagraphProperties: { ...(previous == null ? {} : normalizeDocxParagraphProperties(previous)), ...values } }
  delete result.attrs.outlineLevel
  if ('indentFirstLine' in values) result.attrs.indentFirstLineChars = values.indentFirstLineChars ?? null
  if ('spaceBefore' in values) result.attrs.spaceBeforeAuto = null
  if ('spaceAfter' in values) result.attrs.spaceAfterAuto = null
  if ('outlineLevel' in values) {
    result.type = values.outlineLevel === 0 ? 'docParagraph' : 'docHeading'
    result.attrs.level = values.outlineLevel || null
    result.attrs.outlineOnly = values.outlineLevel === 0 ? null : true
  }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
export function docxParagraphPropertiesOperation(source: DocxPmNode, edited: DocxPmNode, anchor: DocxAnchor, schema?: Schema) {
  if (!schema) throw new Error('段落属性缺少当前文档模型')
  const values = normalizeDocxParagraphProperties(edited.attrs?.nativeParagraphProperties)
  const projected = projectDocxParagraphProperties(source, anchor, values, schema)
  if (JSON.stringify(projected) !== JSON.stringify(edited)) throw new Error('段落设置不能与同段正文或其它格式混改，请先保存')
  return { kind: 'setParagraphProperties', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, values }
}
export function replayDocxParagraphProperties(source: DocxPmNode, anchor: DocxAnchor, operation: Record<string, unknown>, schema: Schema) {
  if (operation.kind !== 'setParagraphProperties' || operation.blockId !== anchor.blockId || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
    || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'values'].includes(key))) throw new Error('草稿段落属性字段或来源身份无效')
  return projectDocxParagraphProperties(source, anchor, operation.values, schema)
}
