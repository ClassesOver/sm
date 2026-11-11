import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { AllSelection, TextSelection } from '@tiptap/pm/state'
import { projectClearedDocxParagraph, type DocxAnchor, type DocxClearRange, type DocxPmNode } from './docx-operations'
import type { DocxStyleInfo } from './docx-styles'

function targets(editor: Editor, anchors: DocxAnchor[]) {
  const { from, to, empty } = editor.state.selection
  const result: { pos: number; node: typeof editor.state.doc; ranges: DocxClearRange[] }[] = []
  let unsupported = false
  editor.state.doc.nodesBetween(from, to, (node, pos, parent) => {
    if (parent !== editor.state.doc) return false
    const anchor = anchors.filter(item => item.docxIndex === node.attrs.docxIndex)
    if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || node.attrs.docxIndex == null
      || anchor.length !== 1 || !anchor[0].editable || !anchor[0].blockId || !anchor[0].expectedObjectSha256
      || editor.state.doc.content.content.filter(item => item.attrs.docxIndex === node.attrs.docxIndex).length !== 1) unsupported = true
    else {
      let inline = false; node.forEach(child => { if (!child.isText) inline = true })
      if (inline) unsupported = true
      result.push({ pos, node, ranges: [{ from: empty ? 0 : Math.max(0, from - pos - 1), to: empty ? node.content.size : Math.min(node.content.size, to - pos - 1) }] })
    }
    return false
  })
  return unsupported ? [] : result
}
export function docxClearFormattingUnavailable(editor: Editor, editable: boolean, anchors: DocxAnchor[]): string | null {
  if (!editable || !editor.isEditable) return '当前文档不可编辑或正在保存'
  if (!(editor.state.selection instanceof TextSelection || editor.state.selection instanceof AllSelection) || !targets(editor, anchors).length) return '请选择有唯一来源锚点、不含内联对象的可编辑正文段落'
  return null
}
export function applyDocxClearFormatting(editor: Editor, editable: boolean, anchors: DocxAnchor[]): void {
  const reason = docxClearFormattingUnavailable(editor, editable, anchors)
  if (reason) throw new Error(reason)
  const styles = (editor.storage as unknown as { listNumbering?: { styles?: Map<string, DocxStyleInfo> } }).listNumbering?.styles
  const styleId = [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId ?? null
  const before = editor.state.doc, tr = closeHistory(editor.state.tr)
  for (const { pos, node, ranges } of targets(editor, anchors)) {
    const previous = node.attrs.nativeClearFormatting as { ranges?: DocxClearRange[] } | null
    const allRanges = [...(previous?.ranges ?? []), ...ranges]
    const projected = projectClearedDocxParagraph(node.toJSON() as DocxPmNode, ranges, styleId, editor.schema)
    projected.attrs = { ...projected.attrs, nativeClearFormatting: { ranges: allRanges } }
    tr.replaceWith(pos, pos + node.nodeSize, editor.schema.nodeFromJSON(projected))
  }
  tr.setSelection(editor.state.selection instanceof AllSelection ? new AllSelection(tr.doc) : TextSelection.create(tr.doc, editor.state.selection.anchor, editor.state.selection.head))
  editor.view.dispatch(tr)
  editor.view.focus()
  if (editor.state.doc.eq(before)) throw new Error('清除格式无法安全保存，请先保存已有修改后重试')
}
