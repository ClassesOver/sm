// GenOffice f8c17004 ribbon-tabs.tsx:193–251；Apache-2.0。原函数保留，供Ribbon专用事务及投影复用。
import { Extension } from '@tiptap/core'
import { EditorState, type Transaction } from '@tiptap/pm/state'
import type { Schema } from '@tiptap/pm/model'
import type { DocxPmNode } from './docx-operations'

export const NativeRibbonStyle = Extension.create({ name: 'nativeRibbonStyle', addGlobalAttributes: () => [{ types: ['docParagraph'], attributes: { nativeRibbonStyle: { default: null, rendered: false } } }] })

const DIRECT_MARKS = ['bold', 'italic', 'underline', 'strike'] as const
const DIRECT_TEXT_STYLE_ATTRS = ['color', 'sizeHalfPoints', 'font', 'fontAscii'] as const

/**
 * Word's rule for direct character formatting under a new paragraph style: a
 * property covering more than half of the paragraph's text is dropped from the
 * whole paragraph (it was standing in for the style), a smaller run keeps it.
 */
export function shedMajorityDirectFormatting(tr: Transaction, pos: number): void {
  const node = tr.doc.nodeAt(pos)
  if (!node?.isTextblock) return
  const total = node.textContent.length
  if (total === 0) return
  const covered = new Map<string, number>()
  node.forEach((child) => {
    if (!child.isText) return
    const len = child.text!.length
    for (const m of child.marks) {
      if ((DIRECT_MARKS as readonly string[]).includes(m.type.name)) {
        covered.set(m.type.name, (covered.get(m.type.name) ?? 0) + len)
      } else if (m.type.name === 'docTextStyle') {
        for (const a of DIRECT_TEXT_STYLE_ATTRS) {
          if (m.attrs[a] != null) covered.set(`ts:${a}`, (covered.get(`ts:${a}`) ?? 0) + len)
        }
      }
    }
  })
  const shed = [...covered].filter(([, n]) => n * 2 > total).map(([k]) => k)
  if (shed.length === 0) return
  const start = pos + 1
  const end = pos + node.nodeSize - 1
  const schema = tr.doc.type.schema
  for (const k of shed) if (!k.startsWith('ts:')) tr.removeMark(start, end, schema.marks[k])
  const attrsToClear = shed.filter((k) => k.startsWith('ts:')).map((k) => k.slice(3))
  if (attrsToClear.length === 0) return
  const type = schema.marks.docTextStyle
  const jobs: Array<{ from: number; to: number; attrs: Record<string, unknown> | null }> = []
  node.forEach((child, offset) => {
    const m = child.marks.find((mm) => mm.type === type)
    if (!m || !attrsToClear.some((a) => m.attrs[a] != null)) return
    const attrs = { ...m.attrs }
    for (const a of attrsToClear) attrs[a] = null
    const keep = Object.values(attrs).some((v) => v != null && v !== false)
    jobs.push({
      from: start + offset,
      to: start + offset + child.nodeSize,
      attrs: keep ? attrs : null,
    })
  })
  for (const job of jobs) {
    tr.removeMark(job.from, job.to, type)
    if (job.attrs) tr.addMark(job.from, job.to, type.create(job.attrs))
  }
}


/** 草稿意图只记录来源样式应用；完整段投影必须与源操作等价。 */
export function projectRibbonStyle(source: DocxPmNode, styleId: string, schema: Schema): DocxPmNode {
  if (source.type !== 'docParagraph' || (source.content ?? []).some(node => node.type !== 'text')) throw new Error('此段落暂不支持Ribbon样式应用')
  const doc = schema.nodeFromJSON({ type: 'doc', content: [source] })
  const tr = EditorState.create({ schema, doc }).tr
  tr.setNodeMarkup(0, undefined, { ...doc.firstChild!.attrs, styleId, nativeRibbonStyle: true })
  shedMajorityDirectFormatting(tr, 0)
  return tr.doc.firstChild!.toJSON() as DocxPmNode
}
