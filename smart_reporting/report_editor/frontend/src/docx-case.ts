import type { Editor } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import { Mark } from '@tiptap/pm/model'
import type { DocxAnchor } from './docx-operations'
import { applyCase, transformCase, selectionText, type CaseMode } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/case-transform'

/** replaceParagraph 按原 run 长度分配文字；统一格式段落才能安全处理 ß 等变长转换。 */
export function docxCaseUnavailable(editor: Editor, editable: boolean, anchors: DocxAnchor[]): string | null {
  if (!editable || !editor.isEditable) return '当前文档不可编辑或正在保存'
  const selection = editor.state.selection
  if (!(selection instanceof TextSelection) || selection.empty) return '请先选择需要转换的文字'
  const { $from, $to } = selection
  if ($from.depth !== 1 || !$from.sameParent($to) || !['docParagraph', 'docHeading', 'docListItem'].includes($from.parent.type.name)) return '请选择同一正文段落内的文字'
  const node = $from.parent, index = node.attrs.docxIndex
  const matches = anchors.filter(anchor => anchor.docxIndex === index)
  if (index == null || matches.length !== 1 || !matches[0].editable || !matches[0].blockId || !matches[0].expectedObjectSha256) return '请选择有唯一来源锚点的可编辑正文段落'
  let safe = true
  const marks = node.firstChild?.marks ?? []
  node.forEach(child => {
    if (!child.isText || child.marks.some(mark => mark.type.name === 'link') || !Mark.sameSet(marks, child.marks)) safe = false
  })
  return safe ? null : '大小写转换暂仅支持格式统一、不含链接或内联对象的正文段落'
}

export function applyDocxCase(editor: Editor, editable: boolean, anchors: DocxAnchor[], mode: CaseMode): void {
  const reason = docxCaseUnavailable(editor, editable, anchors)
  if (reason) throw new Error(reason)
  const before = editor.state.doc, selected = selectionText(editor)
  if (!applyCase(editor, mode) || (transformCase(selected, mode) !== selected && editor.state.doc.eq(before))) throw new Error('当前转换无法安全保存，请先保存已有修改后重试')
}
