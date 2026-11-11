import { Extension } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { docxOperations, type DocxPmNode } from './docx-operations'
import { normalizeDocxRulerIndent, type DocxRulerIndentValues } from '../../../reporting/doc_engine/bridge/docx-ruler-indent'
export { normalizeDocxRulerIndent, type DocxRulerIndentValues }

export interface DocxRulerIndentAnchor {
  blockId: string
  expectedObjectSha256: string
  editable: boolean
  rulerIndentEditable?: boolean
  rulerIndentReadOnlyReason?: string | null
}
export const NativeDocxRulerIndent = Extension.create({
  name: 'nativeDocxRulerIndent',
  addGlobalAttributes: () => [{ types: ['docParagraph', 'docHeading'], attributes: { nativeRulerIndent: { default: null, rendered: false } } }],
})

/** 标尺使用有符号 twips；与旧工具栏的 720 twips 步进协议分开。 */
function assertSource(source: DocxPmNode, anchor: DocxRulerIndentAnchor) {
  if (!anchor.editable || anchor.rulerIndentEditable !== true || !['docParagraph', 'docHeading'].includes(source.type)
    || source.attrs?.bidi === true || source.attrs?.bidiInferred === true || source.attrs?.bidiInherited === true
    || source.attrs?.indentFirstLineChars != null && source.attrs.indentFirstLineChars !== 0) {
    throw new Error(anchor.rulerIndentReadOnlyReason ?? '此来源段落暂不支持标尺缩进')
  }
}
export function projectDocxRulerIndent(source: DocxPmNode, anchor: DocxRulerIndentAnchor, value: unknown): DocxPmNode {
  assertSource(source, anchor)
  const values = normalizeDocxRulerIndent(value), previous = source.attrs?.nativeRulerIndent
  const merged = { ...(previous == null ? {} : normalizeDocxRulerIndent(previous)), ...values }
  const result = structuredClone(source)
  result.attrs = { ...result.attrs, nativeRulerIndent: merged,
    ...(values.leftTwips !== undefined ? { indentLeft: values.leftTwips } : {}),
    ...(values.firstLineTwips !== undefined ? { indentFirstLine: values.firstLineTwips } : {}) }
  return result
}
function withoutIntent(source: DocxPmNode): DocxPmNode {
  const result = structuredClone(source)
  if (result.attrs) delete result.attrs.nativeRulerIndent
  return result
}
/** 只持久化显式标尺意图；同段正文或其它格式改变必须先保存。 */
export function docxRulerIndentOperation(source: DocxPmNode, edited: DocxPmNode, anchor: DocxRulerIndentAnchor) {
  if (edited.attrs?.nativeRulerIndent == null) return null
  const values = normalizeDocxRulerIndent(edited.attrs.nativeRulerIndent)
  const projected = projectDocxRulerIndent(source, anchor, values)
  if (JSON.stringify(withoutIntent(projected)) !== JSON.stringify(withoutIntent(edited))) throw new Error('标尺缩进不能与同段正文或其它格式混改，请先保存')
  const changed = Object.entries(values).some(([key, value]) => source.attrs?.[key === 'leftTwips' ? 'indentLeft' : 'indentFirstLine'] !== value)
  return changed ? { kind: 'setParagraphRulerIndent', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, ...values } : null
}
export function replayDocxRulerIndent(source: DocxPmNode, anchor: DocxRulerIndentAnchor, operation: Record<string, unknown>): DocxPmNode {
  if (operation.kind !== 'setParagraphRulerIndent' || operation.blockId !== anchor.blockId || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
    || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'leftTwips', 'firstLineTwips'].includes(key))) throw new Error('草稿标尺缩进字段或来源身份无效')
  const { kind: _kind, blockId: _blockId, expectedObjectSha256: _hash, ...values } = operation
  return projectDocxRulerIndent(source, anchor, values)
}

export function docxRulerParagraphReason(editor: Editor, anchors: Array<DocxRulerIndentAnchor & { docxIndex: number; paragraphLayoutEditable?: boolean; tabStopsEditable?: boolean; tabStopsReadOnlyReason?: string | null }>, kind: string) {
  const { $from, $to } = editor.state.selection, node = $from.parent
  if ($from.depth !== 1 || $to.depth !== 1 || !$from.sameParent($to) || !['docParagraph', 'docHeading'].includes(node.type.name)) return '仅支持原有正文或标题单段的标尺缩进'
  const matches = anchors.filter(item => item.docxIndex === node.attrs.docxIndex), anchor = matches.length === 1 ? matches[0] : undefined
  if (kind === 'tabs' && anchor?.tabStopsEditable !== true) return anchor?.tabStopsReadOnlyReason ?? '此来源段落暂不支持制表位编辑'
  if (['indentLeft', 'indentFirstLine', 'indentHanging'].includes(kind) && anchor?.rulerIndentEditable !== true) return anchor?.rulerIndentReadOnlyReason ?? '此来源段落暂不支持标尺缩进'
  return anchor?.editable && anchor.paragraphLayoutEditable !== false ? null : '此段落缺少可编辑来源布局锚点'
}

export function applyDocxRulerIndent(editor: Editor, anchors: Array<DocxRulerIndentAnchor & { docxIndex: number }>, attrs: { indentLeft?: number; indentFirstLine?: number }) {
  const { $from, $to } = editor.state.selection
  if (!editor.isEditable || $from.depth !== 1 || $to.depth !== 1 || !$from.sameParent($to)) throw new Error('请选择同一可编辑原有段落')
  const matches = anchors.filter(anchor => anchor.docxIndex === $from.parent.attrs.docxIndex)
  if (matches.length !== 1) throw new Error('标尺段落来源锚点不唯一')
  const values = { ...(attrs.indentLeft !== undefined ? { leftTwips: attrs.indentLeft } : {}), ...(attrs.indentFirstLine !== undefined ? { firstLineTwips: attrs.indentFirstLine } : {}) }
  const projected = projectDocxRulerIndent($from.parent.toJSON(), matches[0]!, values)
  const before = editor.state.doc
  const tr = closeHistory(editor.state.tr).setNodeMarkup($from.before(1), undefined, projected.attrs)
  if (tr.doc.eq(before)) return
  docxOperations(before.toJSON(), tr.doc.toJSON(), anchors)
  editor.view.dispatch(tr)
  if (editor.state.doc === before) throw new Error('标尺缩进与现有编辑不兼容，请先保存')
  editor.view.dispatch(closeHistory(editor.state.tr))
}
