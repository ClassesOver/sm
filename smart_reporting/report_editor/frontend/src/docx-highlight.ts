import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import type { DocxAnchor, DocxPmNode } from './docx-operations'

// GenOffice f8c17004 Ribbon.tsx HIGHLIGHTS; white is legal OOXML but not a source palette swatch.
export const DOCX_HIGHLIGHTS = ['yellow', 'green', 'cyan', 'magenta', 'blue', 'red', 'darkBlue', 'darkCyan', 'darkGreen', 'darkMagenta', 'darkRed', 'darkYellow', 'darkGray', 'lightGray', 'black'] as const
export function safeDocxHighlight(value: unknown): string {
  if (typeof value !== 'string' || ![...DOCX_HIGHLIGHTS, 'white', 'none'].includes(value)) throw new Error('文字高亮颜色无效；仅支持 OOXML 高亮色名或 none')
  return value
}
const isStyle = (type: string) => ['docTextStyle', 'textStyle'].includes(type)
export function highlightMap(node: DocxPmNode): unknown[] {
  return (node.content ?? []).flatMap(run => Array.from({ length: run.type === 'text' ? (run.text ?? '').length : 0 }, () => run.marks?.find(mark => isStyle(mark.type))?.attrs?.highlight ?? null))
}
export function paragraphHighlight(node: DocxPmNode): string | null | undefined {
  const values = highlightMap(node)
  return values.length && values.every(value => value === values[0]) ? values[0] as string | null : undefined
}
export function withoutHighlight(node: DocxPmNode): DocxPmNode {
  return { ...node, content: node.content?.map(run => ({ ...run, marks: (run.marks ?? []).flatMap(mark => {
    if (!isStyle(mark.type)) return [mark]
    const attrs = Object.fromEntries(Object.entries(mark.attrs ?? {}).filter(([key]) => key !== 'highlight'))
    return Object.values(attrs).some(value => value != null && value !== false) ? [{ ...mark, attrs }] : []
  }) })) }
}
/** No table/cursor-formatting claim: a selection within one anchored body paragraph applies to its whole text. */
export function highlightTarget(editor: Editor, anchors: DocxAnchor[]) {
  const { $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1 || $from.before(1) !== $to.before(1)) return undefined
  const node = $from.node(1)
  const matches = anchors.filter(anchor => node.attrs.docxIndex != null && anchor.docxIndex === node.attrs.docxIndex)
  if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || !node.textContent
    || node.content.content.some(child => !child.isText) || matches.length !== 1 || !matches[0].editable
    || !matches[0].blockId || !matches[0].expectedObjectSha256
    || editor.state.doc.content.content.filter(item => item.attrs.docxIndex === node.attrs.docxIndex).length !== 1) return undefined
  return { node, from: $from.start(1), to: $from.end(1) }
}
export function applyParagraphHighlight(editor: Editor, anchors: DocxAnchor[], value: unknown) {
  const highlight = safeDocxHighlight(value)
  const target = highlightTarget(editor, anchors)
  const mark = editor.schema.marks.docTextStyle
  if (!editor.isEditable || !target || !mark) return false
  const tr = closeHistory(editor.state.tr)
  // A fresh mark per leaf keeps every unrelated property and hyperlink metadata.
  target.node.forEach((run, offset) => {
    const old = run.marks.find(item => item.type === mark)
    const from = target.from + offset
    tr.addMark(from, from + run.nodeSize, mark.create({ ...old?.attrs, highlight }))
  })
  if (tr.docChanged) editor.view.dispatch(tr)
  editor.commands.focus()
  return true
}
