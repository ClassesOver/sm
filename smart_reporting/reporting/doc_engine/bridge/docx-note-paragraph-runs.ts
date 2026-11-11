import type { Run } from '../packages/docx-engine/src/types'

/** 只重建notes-safe来源段落；原XML及链接元数据只能从来源run继承。 */
export function compileNoteParagraphRuns(source: Run[], pieces: unknown, noteOperations: Record<string, any>[], allocated: Map<number, Run>, blockId: string,
  applyStyle: (run: Run, value: unknown) => Run, emptyRun?: Run): Run[] {
  function fail(): never { throw new Error('docx_note_paragraph_plan_invalid') }
  if (!Array.isArray(pieces) || pieces.length > 40000) fail()
  let offset = 0, referenceIndex = 0
  const spans = source.map(run => { const from = offset; offset += run.noteRef ? 1 : run.text.length; return { run, from, to: offset, referenceIndex: run.noteRef ? referenceIndex++ : -1 } })
  const full = spans.map(span => span.run.noteRef ? '\uFFFC' : span.run.text).join('')
  const boundary = (at: unknown): at is number => Number.isSafeInteger(at) && Number(at) >= 0 && Number(at) <= full.length
    && !(Number(at) > 0 && Number(at) < full.length && /[\uD800-\uDBFF]/.test(full[Number(at) - 1]!) && /[\uDC00-\uDFFF]/.test(full[Number(at)]!))
  const keys = (piece: Record<string, any>, allowed: string[]) => { if (Object.keys(piece).some(key => !allowed.includes(key))) fail() }
  const result: Run[] = [], usedSource = new Set<number>(), usedNew = new Set<number>()
  let previousTo = 0, finalOffset = 0
  for (const raw of pieces) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail()
    const piece = raw as Record<string, any>, out: Run[] = []
    if ('sourceFrom' in piece) {
      keys(piece, ['sourceFrom', 'sourceTo', 'style'])
      if (!boundary(piece.sourceFrom) || !boundary(piece.sourceTo) || piece.sourceFrom >= piece.sourceTo || piece.sourceFrom < previousTo) fail()
      previousTo = piece.sourceTo
      for (const span of spans) if (span.from < piece.sourceTo && span.to > piece.sourceFrom) {
        if (span.run.noteRef) fail()
        out.push({ ...structuredClone(span.run), text: span.run.text.slice(Math.max(span.from, piece.sourceFrom) - span.from, Math.min(span.to, piece.sourceTo) - span.from) })
      }
    } else if ('text' in piece) {
      keys(piece, ['text', 'inheritFrom', 'style'])
      if (typeof piece.text !== 'string' || !piece.text || !piece.text.isWellFormed() || /[\uFFFE\uFFFF]/.test(piece.text) || piece.text.length > 20000 || /[\x00-\x08\x0b-\x1f]/.test(piece.text) || !boundary(piece.inheritFrom)) fail()
      const inherited = !source.length && piece.inheritFrom === 0 ? emptyRun : spans.find(span => span.from <= piece.inheritFrom && span.to > piece.inheritFrom)?.run
      if (!inherited || (source.length > 0 && !inherited.text && !inherited.noteRef)) fail()
      const plain = structuredClone(inherited)
      delete plain.noteRef
      out.push({ ...plain, text: piece.text })
    } else if ('referenceIndex' in piece) {
      keys(piece, ['noteKind', 'noteId', 'referenceIndex'])
      const span = spans.find(span => span.referenceIndex === piece.referenceIndex && span.run.noteRef)
      if (!span || usedSource.has(piece.referenceIndex) || span.run.noteRef!.kind !== piece.noteKind || span.run.noteRef!.id !== piece.noteId
        || noteOperations.some(op => op.kind === 'deleteNote' && op.noteKind === piece.noteKind && op.noteId === piece.noteId)) fail()
      if (span.from < previousTo) fail()
      previousTo = span.to; usedSource.add(piece.referenceIndex); out.push(structuredClone(span.run))
    } else if ('noteOperationIndex' in piece) {
      keys(piece, ['noteOperationIndex'])
      const marker = allocated.get(piece.noteOperationIndex), op = noteOperations[piece.noteOperationIndex]
      if (!marker || !op || op.kind !== 'insertNote' || op.blockId !== blockId || usedNew.has(piece.noteOperationIndex) || op.offset !== finalOffset) fail()
      usedNew.add(piece.noteOperationIndex); out.push(structuredClone(marker))
    } else fail()
    for (let run of out) {
      if ('style' in piece) run = applyStyle(run, piece.style)
      finalOffset += run.noteRef ? 1 : run.text.length
      if (finalOffset > 20000) fail()
      result.push(run)
    }
  }
  for (const span of spans) if (span.run.noteRef && !usedSource.has(span.referenceIndex)
    && !noteOperations.some(op => op.kind === 'deleteNote' && op.noteKind === span.run.noteRef!.kind && op.noteId === span.run.noteRef!.id)) fail()
  noteOperations.forEach((op, index) => { if (op.kind === 'insertNote' && op.blockId === blockId && !usedNew.has(index)) fail() })
  return result
}
