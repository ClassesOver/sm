import type { Editor } from '@tiptap/core'
import type { DocxAnchor, DocxPmNode } from './docx-operations'

export type ParagraphVerticalAlign = 'baseline' | 'superscript' | 'subscript'
const textStyle = (type: string) => type === 'docTextStyle' || type === 'textStyle'
export function verticalAlignMap(node: DocxPmNode): unknown[] {
  return (node.content ?? []).flatMap(run => Array.from({ length: run.type === 'text' ? (run.text ?? '').length : 0 }, () => run.marks?.find(mark => textStyle(mark.type))?.attrs?.vertAlign ?? 'baseline'))
}
export function paragraphVerticalAlign(node: DocxPmNode): ParagraphVerticalAlign | undefined {
  const values = (node.content ?? []).filter(run => run.type === 'text' && !!run.text).map(run => {
    const value = run.marks?.find(mark => textStyle(mark.type))?.attrs?.vertAlign
    if (value != null && !['baseline', 'superscript', 'subscript'].includes(String(value))) throw new Error('文字上下标状态无效')
    return value == null || value === 'baseline' ? 'baseline' : value as ParagraphVerticalAlign
  })
  return values.length && values.every(value => value === values[0]) ? values[0] : undefined
}
/** Vertical alignment is independent of font, color, emphasis and link metadata. */
export function withoutVerticalAlign(node: DocxPmNode): DocxPmNode {
  return { ...node, content: node.content?.map(run => ({ ...run, marks: (run.marks ?? []).flatMap(mark => {
    if (!textStyle(mark.type)) return [mark]
    const attrs = Object.fromEntries(Object.entries(mark.attrs ?? {}).filter(([key]) => key !== 'vertAlign'))
    return Object.values(attrs).some(value => value != null && value !== false) ? [{ ...mark, attrs }] : []
  }) })) }
}
export function verticalAlignTarget(editor: Editor, anchors: DocxAnchor[]) {
  const { $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1 || $from.before(1) !== $to.before(1)) return undefined
  const node = $from.node(1)
  if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || !node.textContent
    || !anchors.some(anchor => anchor.docxIndex === node.attrs.docxIndex && anchor.editable)) return undefined
  return { node, from: $from.start(1), to: $from.end(1) }
}
export function toggleParagraphVerticalAlign(editor: Editor, anchors: DocxAnchor[], kind: 'superscript' | 'subscript') {
  const target = verticalAlignTarget(editor, anchors)
  if (!editor.isEditable || !target) return false
  const value = paragraphVerticalAlign(target.node.toJSON()) === kind ? null : kind
  return editor.chain().focus().setTextSelection({ from: target.from, to: target.to }).setMark('docTextStyle', { vertAlign: value }).run()
}
