import { createHash } from 'node:crypto'
import { buildNotesXml, nextNoteId, parseNotesXml, type NoteKind } from '../packages/docx-engine/src/notes'
import { xmlSegments } from '../packages/docx-engine/src/generate'
import type { NoteInfo, Run } from '../packages/docx-engine/src/types'

export type NoteReferenceAnchor = { blockId: string; expectedObjectSha256: string; referenceIndex: number }
export type NoteAnchor = { id: string; text: string; expectedNoteSha256: string; editable: boolean; reason?: string; references: NoteReferenceAnchor[] }
export type NoteBlock = { blockId: string; expectedObjectSha256: string; editable: boolean; runs: Run[] }
export interface NotesSource { sourceSha256: string; footnotesXml: string | null; endnotesXml: string | null; blocks: NoteBlock[] }
const hash = (value: string) => createHash('sha256').update(value).digest('hex')
function fail(reason: string): never { throw new Error(`docx_note_${reason}`) }
const kinds = ['footnote', 'endnote'] as const
const record = (value: unknown): Record<string, any> => { if (!value || typeof value !== 'object' || Array.isArray(value)) fail('operation_invalid'); return value as Record<string, any> }
const keys = (value: Record<string, any>, allowed: string[]) => { if (Object.keys(value).some(key => !allowed.includes(key))) fail('operation_invalid') }
const validText = (value: unknown): string => { if (typeof value !== 'string' || value.length > 20000 || /[\x00-\x08\x0b-\x1f]/.test(value)) fail('text_invalid'); return value as string }
const simpleNote = (xml: string) => {
  const allowed = new Set(['footnote', 'endnote', 'p', 'pPr', 'r', 'rPr', 't', 'footnoteRef', 'endnoteRef', 'pStyle', 'rStyle', 'b', 'bCs', 'i', 'iCs', 'u', 'strike', 'dstrike', 'color', 'sz', 'szCs', 'rFonts', 'lang', 'vertAlign', 'spacing', 'jc', 'ind', 'keepNext', 'keepLines', 'widowControl', 'contextualSpacing', 'shd', 'highlight'])
  return [...xml.matchAll(/<\/?([\w.-]+):([\w.-]+)\b/g)].every(match => match[1] === 'w' && allowed.has(match[2]!))
}

/** 服务端原始entry哈希绑定(kind,id,source)，不接受客户端XML或part路径。 */
export function createDocxNotesPlanner(source: NotesSource) {
  const originals = { footnote: source.footnotesXml, endnote: source.endnotesXml }
  const entries: Record<NoteKind, Map<string, string>> = { footnote: new Map(), endnote: new Map() }
  const lists: Record<NoteKind, NoteInfo[]> = { footnote: [], endnote: [] }
  const references: Record<NoteKind, Map<string, NoteReferenceAnchor[]>> = { footnote: new Map(), endnote: new Map() }
  const blocks = new Map(source.blocks.map(block => [block.blockId, structuredClone(block)]))
  if (blocks.size !== source.blocks.length) fail('block_identity_invalid')
  for (const block of source.blocks) {
    let index = 0
    for (const run of block.runs) if (run.noteRef) {
      const { kind, id } = run.noteRef, refs = references[kind].get(id) ?? []
      refs.push({ blockId: block.blockId, expectedObjectSha256: block.expectedObjectSha256, referenceIndex: index++ })
      references[kind].set(id, refs)
    }
  }
  const model = { footnotes: [] as NoteAnchor[], endnotes: [] as NoteAnchor[], referenceBlocks: source.blocks.map(({ blockId, expectedObjectSha256, editable, runs }) => ({ blockId, expectedObjectSha256, editable, text: runs.map(run => run.noteRef ? '\uFFFC' : run.text).join('') })), parts: {} as Partial<Record<NoteKind, string>> }
  for (const kind of kinds) {
    const xml = originals[kind]
    if (!xml) continue
    if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(xml)) fail('part_unsupported')
    model.parts[kind] = hash(xml)
    const root = new RegExp(`<w:${kind}s\\b[^>]*>([\\s\\S]*)</w:${kind}s>\\s*$`).exec(xml)
    if (!root) fail('part_unsupported')
    let residue = root[1]!, consumed = 0
    const segments = xmlSegments(xml, `w:${kind}`, 0, xml.length)
    // 原part非note子节点不在engine重建契约内，不能在保存时悄悄丢弃。
    const innerStart = xml.indexOf(root[1]!, root.index)
    for (const segment of segments) {
      residue = residue.slice(0, segment.start - innerStart - consumed) + residue.slice(segment.end - innerStart - consumed)
      consumed += segment.end - segment.start
    }
    if (residue.replace(/<!--[\s\S]*?-->/g, '').trim()) fail('part_unsupported')
    for (const segment of segments) {
      const entry = xml.slice(segment.start, segment.end), open = entry.match(/^<[^>]+>/)?.[0] ?? ''
      if (/\bw:type\s*=/.test(open)) continue
      const id = /\bw:id=["']([^"']+)["']/.exec(open)?.[1]
      if (!id || !/^\d+$/.test(id) || !Number.isSafeInteger(Number(id)) || entries[kind].has(id)) fail('identity_invalid')
      entries[kind].set(id, entry)
    }
    lists[kind] = parseNotesXml(xml, kind)
    if (lists[kind].length !== entries[kind].size) fail('part_unsupported')
    model[`${kind}s`].push(...lists[kind].map(note => {
      const entry = entries[kind].get(note.id)!, editable = simpleNote(entry)
      return { id: note.id, text: note.text, expectedNoteSha256: hash(`${source.sourceSha256}:${kind}:${entry}`), editable,
        ...(editable ? {} : { reason: '此注释包含复杂对象或域，保留原文；暂不能修改文本' }), references: references[kind].get(note.id) ?? [] }
    }))
  }
  for (const kind of kinds) for (const id of references[kind].keys()) if (!entries[kind].has(id)) fail('reference_identity_invalid')
  return {
    model: structuredClone(model),
    plan(operations: readonly unknown[], finalParagraphs: ReadonlySet<string> = new Set()) {
      const next = { footnote: structuredClone(lists.footnote), endnote: structuredClone(lists.endnote) }
      const changed = new Set<NoteKind>(), touched = new Set<string>(), changedBlocks = new Map<string, Run[]>(), allocated = new Map<number, Run>()
      const originalBlock = (operation: Record<string, any>) => {
        const block = blocks.get(operation.blockId)
        if (!block || operation.expectedObjectSha256 !== block.expectedObjectSha256) fail('block_anchor_invalid')
        if (!block.editable) fail('reference_unsupported')
        return block
      }
      for (const [operationIndex, raw] of operations.entries()) {
        const op = record(raw), kind = op.noteKind as NoteKind
        if (!kinds.includes(kind)) fail('kind_invalid')
        if (op.kind === 'insertNote') {
          keys(op, ['kind', 'noteKind', 'blockId', 'expectedObjectSha256', 'offset', 'text'])
          const block = originalBlock(op), text = validText(op.text), offset = op.offset
          const currentRuns = changedBlocks.get(block.blockId) ?? block.runs
          const full = currentRuns.map(run => run.noteRef ? '\uFFFC' : run.text).join('')
          if (!Number.isSafeInteger(offset) || offset < 0 || !finalParagraphs.has(block.blockId) && (offset > full.length || offset > 0 && offset < full.length && /[\uD800-\uDBFF]/.test(full[offset - 1]!) && /[\uDC00-\uDFFF]/.test(full[offset]!))) fail('offset_invalid')
          const id = nextNoteId([...lists[kind], ...next[kind], ...[...references[kind].keys()].map(id => ({ id, text: '' }))]), runs: Run[] = [], marker: Run = { text: String(next[kind].length + 1), noteRef: { kind, id } }
          allocated.set(operationIndex, marker)
          if (finalParagraphs.has(block.blockId)) {
            next[kind].push({ id, text }); changed.add(kind); continue
          }
          let cursor = 0, inserted = false
          for (const run of currentRuns) {
            const length = run.noteRef ? 1 : run.text.length
            const local = offset - cursor
            if (!inserted && local >= 0 && local <= length) {
              if (local > 0 && local < length && (run.noteRef || run.refField || run.xeTerm || run.ins || run.del)) fail('reference_unsupported')
              if (local > 0) runs.push(run.noteRef ? structuredClone(run) : { ...run, text: run.text.slice(0, local) })
              runs.push(marker); inserted = true
              if (local < length) runs.push(run.noteRef ? structuredClone(run) : { ...run, text: run.text.slice(local) })
            } else runs.push(structuredClone(run))
            cursor += length
          }
          if (!inserted) runs.push(marker)
          next[kind].push({ id, text }); changedBlocks.set(block.blockId, runs); changed.add(kind)
          continue
        }
        if (op.kind !== 'updateNote' && op.kind !== 'deleteNote') fail('operation_invalid')
        keys(op, ['kind', 'noteKind', 'noteId', 'expectedNoteSha256', op.kind === 'updateNote' ? 'text' : 'expectedReferences'])
        const anchor = model[`${kind}s`].find(note => note.id === op.noteId)
        if (!anchor || anchor.expectedNoteSha256 !== op.expectedNoteSha256) fail('anchor_invalid')
        const identity = `${kind}:${op.noteId}`
        if (touched.has(identity)) fail('batch_conflict')
        touched.add(identity)
        if (op.kind === 'updateNote') {
          if (!anchor.editable) fail('text_unsupported')
          const note = next[kind].find(note => note.id === op.noteId)!
          note.text = validText(op.text); delete note.richParas
        } else {
          if (JSON.stringify(op.expectedReferences) !== JSON.stringify(anchor.references)) fail('reference_anchor_invalid')
          for (const ref of anchor.references) {
            const block = originalBlock(ref)
            if (finalParagraphs.has(block.blockId)) continue
            changedBlocks.set(block.blockId, (changedBlocks.get(block.blockId) ?? block.runs).filter(run => run.noteRef?.kind !== kind || run.noteRef.id !== op.noteId).map(run => structuredClone(run)))
          }
          next[kind] = next[kind].filter(note => note.id !== op.noteId)
        }
        changed.add(kind)
      }
      const parts: Partial<Record<NoteKind, string>> = {}
      for (const kind of changed) parts[kind] = buildNotesXml(kind, next[kind], originals[kind])
      return { ...(changed.has('footnote') ? { footnotes: next.footnote } : {}), ...(changed.has('endnote') ? { endnotes: next.endnote } : {}), blocks: changedBlocks, parts, allocated }
    },
  }
}
