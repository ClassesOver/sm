import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { docxDropCapAttribute, normalizeDocxDropCap, type DocxDropCap } from '../../../reporting/doc_engine/bridge/docx-drop-cap'
import type { NativeOperation } from './native-draft'

const paragraphs = ['docParagraph', 'docHeading', 'docListItem']
function selected(editor: Editor, anchors: DocxAnchor[]) {
  const { $from, $to } = editor.state.selection
  if (!editor.isEditable || $from.depth !== 1 || $to.depth !== 1) return []
  const result: { node: typeof $from.parent; pos: number }[] = []
  let invalid = false
  editor.state.doc.forEach((node, pos, index) => {
    if (index < $from.index(0) || index > $to.index(0)) return
    const matches = anchors.filter(a => a.docxIndex === node.attrs.docxIndex)
    if (!paragraphs.includes(node.type.name) || node.attrs.frame || node.attrs.frameBox
      || node.attrs.docxIndex != null && (matches.length !== 1 || !matches[0]!.editable || matches[0]!.dropCapEditable === false)) invalid = true
    else result.push({ node, pos })
  })
  return invalid ? [] : result
}
export function docxDropCapUnavailable(editor: Editor, anchors: DocxAnchor[]) {
  return selected(editor, anchors).length ? null : '请选择可编辑的正文、标题或列表段落；定位框和受保护对象不支持首字下沉'
}
export function applyDocxDropCap(editor: Editor, anchors: DocxAnchor[], value: DocxDropCap['type'] | null) {
  const targets = selected(editor, anchors)
  if (!targets.length) throw new Error(docxDropCapUnavailable(editor, anchors)!)
  const cap = value === null ? null : JSON.stringify(normalizeDocxDropCap({ type: value, lines: 3 }))
  const tr = closeHistory(editor.state.tr)
  for (const { node, pos } of targets) if ((node.attrs.dropCap ?? null) !== cap) tr.setNodeMarkup(pos, undefined, { ...node.attrs, dropCap: cap })
  if (!tr.docChanged) return
  editor.view.dispatch(tr)
  editor.view.dispatch(closeHistory(editor.state.tr))
  editor.view.focus()
}
/** 独立 pPr 意图先剥离；原正文/样式编译器仍负责其余编辑，首字下沉最后合成。 */
export function normalizeDocxDropCaps(original: DocxPmNode, current: DocxPmNode, anchors: readonly DocxAnchor[]) {
  const normalized = structuredClone(current), operations: NativeOperation[] = []
  for (const node of normalized.content ?? []) {
    const source = original.content?.find(p => p.attrs?.docxIndex != null && p.attrs.docxIndex === node.attrs?.docxIndex)
    if (!source || !paragraphs.includes(node.type) || (source.attrs?.dropCap ?? null) === (node.attrs?.dropCap ?? null)) continue
    if (node.attrs?.nativeClearFormatting && node.attrs.dropCap == null) continue
    const matches = anchors.filter(a => a.docxIndex === node.attrs?.docxIndex)
    if (matches.length !== 1 || !matches[0]!.editable || matches[0]!.dropCapEditable === false || source.attrs?.frame || source.attrs?.frameBox) throw new Error('首字下沉来源不可编辑')
    const anchor = matches[0]!, value = docxDropCapAttribute(node.attrs?.dropCap)
    operations.push({ kind: 'setParagraphDropCap', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, value })
    node.attrs = { ...node.attrs, dropCap: node.attrs?.nativeClearFormatting ? null : source.attrs?.dropCap ?? null }
  }
  return { current: normalized, operations }
}
export function replayDocxDropCap(node: DocxPmNode, anchor: DocxAnchor, operation: NativeOperation) {
  if (!anchor.editable || anchor.dropCapEditable === false || !paragraphs.includes(node.type) || node.attrs?.frame || node.attrs?.frameBox
    || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
    || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'value'].includes(key))) throw new Error('草稿首字下沉来源或字段无效')
  const value = normalizeDocxDropCap(operation.value)
  node.attrs = { ...node.attrs, dropCap: value ? JSON.stringify(value) : null }
}
