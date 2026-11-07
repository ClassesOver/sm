import type { Editor } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import type { DocxAnchor } from './docx-operations'
import { safeDocxLink, validDocxLinkRange } from './docx-operations'
export interface DocxLinkSelection {
  from: number; to: number; paragraphPos: number; snapshot: string
  href?: string; attrs?: Record<string, unknown>; hasLink: boolean
}
export const linkSelectionUnavailable = '请选择已有可编辑正文段落中的文字；新增段落、表格及复杂对象暂不支持链接写回'
export function docxLinkSelection(editor: Editor, anchors: DocxAnchor[]): DocxLinkSelection | undefined {
  const { selection } = editor.state, { $from, $to } = selection
  if (!(selection instanceof TextSelection) || !editor.isEditable || !editor.schema.marks.link
    || $from.depth !== 1 || $to.depth !== 1 || $from.parent !== $to.parent
    || !['docParagraph', 'docHeading', 'docListItem'].includes($from.parent.type.name)
    || !anchors.some(anchor => anchor.editable && anchor.docxIndex === $from.parent.attrs.docxIndex)) return
  const parent = $from.parent
  let complex = false
  const runs: { from: number; to: number; attrs?: Record<string, unknown> }[] = []
  parent.forEach((node, offset) => {
    if (!node.isText) complex = true
    runs.push({ from: offset, to: offset + node.nodeSize, attrs: node.marks.find(mark => mark.type.name === 'link')?.attrs })
  })
  if (complex) return
  let from = $from.parentOffset, to = $to.parentOffset
  if (selection.empty) {
    const index = runs.findIndex(run => run.attrs && run.from <= from && run.to > from)
    const at = index >= 0 ? index : runs.findIndex(run => run.attrs && run.to === from)
    if (at < 0) return
    let start = at, end = at
    while (start > 0 && JSON.stringify(runs[start - 1].attrs) === JSON.stringify(runs[at].attrs)) start--
    while (end + 1 < runs.length && JSON.stringify(runs[end + 1].attrs) === JSON.stringify(runs[at].attrs)) end++
    from = runs[start].from; to = runs[end].to
  }
  if (!validDocxLinkRange(parent.textContent, from, to)) return
  const touched = runs.filter(run => run.from < to && run.to > from)
  const attrs = touched[0]?.attrs
  const uniform = attrs && touched.every(run => run.attrs?.href === attrs.href)
  return { from: $from.start() + from, to: $from.start() + to, paragraphPos: $from.before(), snapshot: JSON.stringify(parent.toJSON()),
    hasLink: touched.some(run => !!run.attrs), ...(uniform ? { href: String(attrs.href), attrs } : {}) }
}
export function applyDocxLink(editor: Editor, selection: DocxLinkSelection, value: string | null): boolean {
  if (!editor.isEditable || JSON.stringify(editor.state.doc.nodeAt(selection.paragraphPos)?.toJSON()) !== selection.snapshot) throw new Error('选区已改变，请重新选择链接文字')
  const href = value === null ? null : safeDocxLink(value)
  const mark = editor.schema.marks.link
  const tr = editor.state.tr.setSelection(TextSelection.create(editor.state.doc, selection.from, selection.to))
  if (href === null) tr.removeMark(selection.from, selection.to, mark)
  else editor.state.doc.nodesBetween(selection.from, selection.to, (node, pos) => {
    if (!node.isText) return
    const attrs = node.marks.find(item => item.type === mark)?.attrs
    tr.addMark(Math.max(selection.from, pos), Math.min(selection.to, pos + node.nodeSize), mark.create({ ...attrs, href, rId: null }))
  })
  editor.view.dispatch(tr)
  editor.view.focus()
  return editor.state.doc.eq(tr.doc)
}
