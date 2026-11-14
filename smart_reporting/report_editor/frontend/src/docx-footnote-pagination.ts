import { loadDocxZip } from '../../../reporting/doc_engine/packages/docx-engine/src/zip-load'
import type { Node as PmNode } from '@tiptap/pm/model'
import type { NoteInfo, SectionInfo, SectionSettings } from '@genoffice/docx-engine'
import { buildNotesXml } from '../../../reporting/doc_engine/packages/docx-engine/src/notes'
import { parseDocxOffThread } from './vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread'
import { notesOperationsOf, projectedDocxNotes, type DocxNotesModel, type DocxNoteKind } from './docx-notes'
import { measureNoteHeightDom, noteRowMetrics } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/note-dom'
import { estimateFootnoteHeight, noteRunStyle, resolveNoteStyle } from './vendor/genoffice-docs/apps/docs/src/renderer/line-metrics'
import { currentRevisionDisplay, noteRunsInView } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revision-view'
import { pageOfY, type BlockBox, type BlockMetaOf, type PageNoteItem, type PageSlice } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination'

type Parsed = Awaited<ReturnType<typeof parseDocxOffThread>>

/** 保存使用同一buildNotesXml文本补丁，重新解析实际run；不把旧richParas或纯文本当编辑后的格式。 */
export async function currentDocxNotes(kind: DocxNoteKind, input: { bytes: Uint8Array; parsed: Parsed; doc: PmNode; model?: DocxNotesModel }, stillCurrent: () => boolean): Promise<NoteInfo[]> {
  const list = kind === 'footnote' ? 'footnotes' : 'endnotes'
  const path = `word/${list}.xml`
  const check = () => { if (!stillCurrent()) throw new Error('文档或注释发生变化，请重新打开分页或页眉页脚菜单') }
  check()
  const operations = notesOperationsOf(input.doc.toJSON()).filter(op => op.noteKind === kind)
  if (!operations.length) return notesInCurrentRevisionView(input.parsed[list] ?? [])
  if (!input.model) throw new Error('当前来源未提供注释编辑身份')
  const notes = projectedDocxNotes(input.model, operations).filter(note => note.kind === kind).map(note => {
    const source = input.parsed[list].find(item => item.id === note.id)
    const projected = { ...source, id: note.id, text: note.text }
    if (operations.some(op => op.kind === 'updateNote' && op.noteId === note.id)) delete projected.richParas
    return projected
  })
  const zip = await loadDocxZip(input.bytes); check()
  const original = await zip.file(path)?.async('string'); check()
  zip.file(path, buildNotesXml(kind, notes, original ?? null))
  const bytes = await zip.generateAsync({ type: 'uint8array' }); check()
  const parsed = await parseDocxOffThread(bytes); check()
  return notesInCurrentRevisionView(parsed[list])
}

function notesInCurrentRevisionView(notes: NoteInfo[]): NoteInfo[] {
  const mode = currentRevisionDisplay()
  const marker = typeof document === 'undefined' ? null : document.querySelector<HTMLElement>('.app[data-native-docx-review-state]')
  const hiddenAuthors = new Set<string>(JSON.parse(marker?.dataset.revHiddenAuthors ?? '[]'))
  const insDel = marker?.dataset.revInsDel !== 'false'
  if (mode === 'all' && insDel && hiddenAuthors.size === 0) return notes
  return notes.map(note => {
    const displayed = noteRunsInView(mode, note.richParas)
    const richParas = displayed?.map(para => para.flatMap(run => {
      if (run.del && (!insDel || hiddenAuthors.has(run.del.author))) return []
      if (run.ins && (!insDel || hiddenAuthors.has(run.ins.author))) {
        const { ins: _ins, ...plain } = run
        return [plain]
      }
      return [run]
    }))
    return {
      ...note,
      richParas,
      ...(richParas ? { text: richParas.map(runs => runs.map(run => run.text).join('')).join('\n') } : {}),
    }
  })
}

export const currentFootnotes = (input: Parameters<typeof currentDocxNotes>[1], stillCurrent: () => boolean) => currentDocxNotes('footnote', input, stillCurrent)

function noteNumbers(doc: PmNode, kind: DocxNoteKind) {
  const numbers = new Map<string, number>()
  doc.descendants(node => {
    if (node.type.name === 'docNoteRef' && node.attrs.kind === kind && !numbers.has(String(node.attrs.id))
      && typeof node.attrs.num === 'number' && Number.isFinite(node.attrs.num)) numbers.set(String(node.attrs.id), node.attrs.num)
  })
  return numbers
}

function measuredNote(parsed: Parsed, note: NoteInfo, no: number, sec: SectionSettings, kind: DocxNoteKind): PageNoteItem {
  const style = { ...resolveNoteStyle(parsed, note.styleId, note.spacing), ...noteRunStyle(note.richParas) }
  const metrics = noteRowMetrics(style, sec.docGrid), width = (sec.pageWidth - sec.marginLeft - sec.marginRight) / 15
  const height = measureNoteHeightDom({ ...note, no }, kind, width, metrics.lineHeightPx, metrics.fontSizePt, metrics.fontFamily)
    ?? estimateFootnoteHeight(note.text, width, sec.docGrid, undefined, style, note.richParas)
  return { ...note, no, height, ...metrics }
}

/** 固定源App.tsx:3869：尾注集中在文末，以末节内容宽度参与同一分页流。 */
export function endnotePagination(input: { parsed: Parsed; notes: NoteInfo[]; doc: PmNode; sections: SectionInfo[]; section: SectionSettings }): PageNoteItem[] {
  const numbers = noteNumbers(input.doc, 'endnote'), sec = input.sections.at(-1)?.settings ?? input.section
  return input.notes.map((note, index) => measuredNote(input.parsed, note, numbers.get(note.id) ?? input.parsed.noteNumbers?.[`endnote:${note.id}`] ?? index + 1, sec, 'endnote'))
}

/** 固定源f8c17004 App.tsx:3534/3622/3813脚注collector；引用扫描改为当前PM，度量和归页沿用源规则。 */
export function footnotePagination(input: { parsed: Parsed; notes: NoteInfo[]; doc: PmNode; sections: SectionInfo[]; section: SectionSettings }) {
  const refs = new Map<number, { id: string; no: number }[]>()
  const numbers = noteNumbers(input.doc, 'footnote')
  input.doc.forEach(block => {
    const index = block.attrs.docxIndex
    if (typeof index !== 'number') return
    const found: { id: string; no: number }[] = []
    block.descendants(node => {
      if (node.type.name !== 'docNoteRef' || node.attrs.kind !== 'footnote') return
      const id = String(node.attrs.id)
      found.push({ id, no: numbers.get(id) ?? input.parsed.noteNumbers?.[`footnote:${id}`] ?? input.notes.findIndex(note => note.id === id) + 1 })
    })
    if (found.length) refs.set(index, found)
  })
  const notes = new Map(input.notes.map(note => [note.id, note]))
  const sectionOf = (index: number) => input.sections.find(sec => index <= sec.lastBlockIndex)?.settings ?? input.section
  // 每次分页请求新缓存；fonts.ready之后创建，避免草稿/字体变化留下旧高度。
  const measured = new Map<string, PageNoteItem>()
  const itemOf = (index: number, ref: { id: string; no: number }): PageNoteItem | undefined => {
    const note = notes.get(ref.id)
    if (!note) return
    const sec = sectionOf(index), key = `${index}:${ref.id}:${ref.no}`
    let item = measured.get(key)
    if (!item) {
      item = measuredNote(input.parsed, note, ref.no, sec, 'footnote'); measured.set(key, item)
    }
    return item
  }
  const blockMetaOf: BlockMetaOf = index => {
    const bands = (refs.get(index) ?? []).flatMap(ref => { const item = itemOf(index, ref); return item ? [{ heightPx: item.height }] : [] })
    return bands.length ? { footnoteExtraPx: bands.reduce((sum, band) => sum + band.heightPx, 0), footnoteBands: bands } : undefined
  }
  const pageFootnotesOf = (blocks: BlockBox[], slices: PageSlice[]): PageNoteItem[][] => {
    const out: PageNoteItem[][] = slices.map(() => [])
    for (const block of blocks) {
      if (block.docxIndex === undefined) continue
      const found = refs.get(block.docxIndex) ?? []
      found.forEach((ref, index) => {
        const item = itemOf(block.docxIndex!, ref)
        if (!item) return
        const band = block.noteBands?.length === found.length ? block.noteBands[index] : undefined
        const page = pageOfY(slices, band ? block.top + (block.spaceBeforePx ?? 0) + band.offset : block.top)
        out[page]?.push(item)
      })
    }
    return out
  }
  return { blockMetaOf, pageFootnotesOf, footnotesBeneathText: input.parsed.footnoteProps?.pos === 'beneathText' }
}
