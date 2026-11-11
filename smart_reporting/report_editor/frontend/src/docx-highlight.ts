import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { validDocxLinkRange, type DocxAnchor, type DocxPmNode } from './docx-operations'
import type { Node as PmNode } from '@tiptap/pm/model'

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
/** Keep paragraph bounds stable: shading and borders also use this target. */
export function highlightTarget(editor: Editor, anchors: DocxAnchor[], allowNoteReferences = false) {
  const { $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1 || $from.before(1) !== $to.before(1)) return undefined
  const node = $from.node(1)
  const matches = anchors.filter(anchor => node.attrs.docxIndex != null && anchor.docxIndex === node.attrs.docxIndex)
  if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || !node.textContent
    || node.content.content.some(child => !child.isText && !(allowNoteReferences && ['docNoteRef', 'hardBreak'].includes(child.type.name))) || matches.length !== 1 || !matches[0].editable
    || !matches[0].blockId || !matches[0].expectedObjectSha256
    || editor.state.doc.content.content.filter(item => item.attrs.docxIndex === node.attrs.docxIndex).length !== 1) return undefined
  return { node, from: $from.start(1), to: $from.end(1) }
}
/** A collapsed cursor preserves the existing whole-paragraph formatting behavior. */
export function textFormattingRange(editor: Editor, target: { node: PmNode; from: number; to: number }) {
  const selection = editor.state.selection
  const from = selection.empty ? target.from : selection.from
  const to = selection.empty ? target.to : selection.to
  if (!selection.empty && !validDocxLinkRange(target.node.textBetween(0, target.node.content.size, '', '\uFFFC'), from - target.from, to - target.from)) return undefined
  return { from, to }
}
export function selectedHighlight(editor: Editor, anchors: DocxAnchor[], allowNoteReferences = false) {
  const target = highlightTarget(editor, anchors, allowNoteReferences)
  const range = target && textFormattingRange(editor, target)
  return target && range ? paragraphHighlight(target.node.cut(range.from - target.from, range.to - target.from).toJSON()) : undefined
}
export function applyParagraphHighlight(editor: Editor, anchors: DocxAnchor[], value: unknown, allowNoteReferences = false) {
  const highlight = safeDocxHighlight(value)
  const target = highlightTarget(editor, anchors, allowNoteReferences)
  const mark = editor.schema.marks.docTextStyle
  if (!editor.isEditable || !target || !mark) return false
  const range = textFormattingRange(editor, target)
  if (!range) return false
  const tr = closeHistory(editor.state.tr)
  // A fresh mark per leaf keeps every unrelated property and hyperlink metadata.
  target.node.forEach((run, offset) => {
    if (!run.isText) return
    const old = run.marks.find(item => item.type === mark)
    const from = Math.max(target.from + offset, range.from)
    const to = Math.min(target.from + offset + run.nodeSize, range.to)
    if (from < to) tr.addMark(from, to, mark.create({ ...old?.attrs, highlight }))
  })
  if (tr.docChanged) editor.view.dispatch(tr)
  editor.commands.focus()
  return true
}
