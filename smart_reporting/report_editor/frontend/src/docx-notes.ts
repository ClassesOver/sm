import { compileNoteParagraphRuns, replayNoteParagraphRuns } from './docx-note-paragraph-runs'
import { noteParagraphLayout } from './docx-note-paragraph-layout'
import type { DocxAnchor, DocxPmNode } from './docx-operations'

export type DocxNoteKind = 'footnote' | 'endnote'
export type DocxNoteReference = { blockId: string; expectedObjectSha256: string; referenceIndex: number }
export interface DocxNoteEntry { id: string; text: string; expectedNoteSha256: string; editable: boolean; reason?: string; references: DocxNoteReference[] }
export interface DocxNotesModel { footnotes: DocxNoteEntry[]; endnotes: DocxNoteEntry[]; referenceBlocks?: { blockId: string; expectedObjectSha256: string; editable: boolean; text?:string }[]; parts?: Partial<Record<DocxNoteKind, string>> }
export type DocxNoteOperation = { kind: string; [key: string]: any }
const kinds: DocxNoteKind[] = ['footnote', 'endnote']
function fail(): never { throw new Error('脚注尾注草稿与当前来源不一致或包含不支持的修改') }
const validText = (text: unknown): text is string => typeof text === 'string' && text.length <= 20000 && !/[\x00-\x08\x0b-\x1f]/.test(text)
const clone = <T>(value: T): T => structuredClone(value)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
export function notesOperationsOf(doc: DocxPmNode): DocxNoteOperation[] {
  const operations = doc.attrs?.nativeNotesOperations
  if (operations === undefined || operations === null) return []
  if (!Array.isArray(operations)) fail()
  return clone(operations)
}
function newId(model: DocxNotesModel, inserted: string[], kind: DocxNoteKind): string {
  return String(Math.max(0, ...model[`${kind}s`].map(note => Number.parseInt(note.id, 10)).filter(Number.isSafeInteger), ...inserted.map(Number)) + 1)
}
/** 同服务端分配顺序的显示投影；预测id不作为客户端插入操作字段提交。 */
export function projectedDocxNotes(model: DocxNotesModel, operations: readonly DocxNoteOperation[]) {
  const entries = kinds.flatMap(kind => model[`${kind}s`].map(note => ({ ...clone(note), kind, pending: false, operationIndex: -1 })))
  const allocated: Record<DocxNoteKind, string[]> = { footnote: [], endnote: [] }
  const touched = new Set<string>()
  operations.forEach((op, operationIndex) => {
    if (!op || typeof op !== 'object' || !kinds.includes(op.noteKind)) fail()
    const kind = op.noteKind as DocxNoteKind
    if (op.kind === 'insertNote') {
      if (!validText(op.text) || !Number.isSafeInteger(op.offset) || op.offset < 0 || typeof op.blockId !== 'string' || typeof op.expectedObjectSha256 !== 'string'
        || Object.keys(op).some(key => !['kind', 'noteKind', 'blockId', 'expectedObjectSha256', 'offset', 'text'].includes(key))) fail()
      const id = newId(model, allocated[kind], kind); allocated[kind].push(id)
      entries.push({ id, text: op.text, expectedNoteSha256: '', editable: true, references: [], kind, pending: true, operationIndex })
      return
    }
    const entry = entries.find(entry => entry.kind === kind && entry.id === op.noteId && !entry.pending)
    if (!entry || entry.expectedNoteSha256 !== op.expectedNoteSha256 || touched.has(`${kind}:${entry.id}`)) fail()
    touched.add(`${kind}:${entry.id}`)
    const fields = ['kind', 'noteKind', 'noteId', 'expectedNoteSha256', op.kind === 'updateNote' ? 'text' : 'expectedReferences']
    if (Object.keys(op).some(key => !fields.includes(key))) fail()
    if (op.kind === 'updateNote') { if (!entry.editable || !validText(op.text)) fail(); entry.text = op.text }
    else if (op.kind === 'deleteNote') {
      if (!same(op.expectedReferences, entry.references)) fail()
      entries.splice(entries.indexOf(entry), 1)
    } else fail()
  })
  return entries
}
function sourceBlock(doc: DocxPmNode, anchors: readonly DocxAnchor[], operation: Record<string, any>, model: DocxNotesModel): DocxPmNode {
  const eligibility = model.referenceBlocks?.find(block => block.blockId === operation.blockId && block.expectedObjectSha256 === operation.expectedObjectSha256)
  const anchor = anchors.find(anchor => anchor.blockId === operation.blockId && anchor.expectedObjectSha256 === operation.expectedObjectSha256 && (eligibility ? eligibility.editable : anchor.editable))
  if (!anchor) fail()
  let found: DocxPmNode | undefined
  const walk = (node: DocxPmNode) => { if (node.attrs?.docxIndex === anchor.docxIndex) { if (found) fail(); found = node }; node.content?.forEach(walk) }
  walk(doc)
  if (!found || !['docParagraph', 'docHeading', 'docListItem'].includes(found.type)) fail()
  return found
}
function insertMarker(node: DocxPmNode, offset: number, kind: DocxNoteKind, id: string) {
  const out: DocxPmNode[] = [], marker: DocxPmNode = { type: 'docNoteRef', attrs: { kind, id, num: 1, rawRPr: null } }
  let cursor = 0, inserted = false
  for (const child of node.content ?? []) {
    if (child.type !== 'text' && child.type !== 'docNoteRef' && child.type !== 'hardBreak') fail()
    const length = child.type === 'text' ? (child.text ?? '').length : 1, local = offset - cursor
    if (!inserted && local >= 0 && local <= length) {
      if (child.type === 'text' && local > 0 && local < length && /[\uD800-\uDBFF]/.test(child.text![local - 1]!) && /[\uDC00-\uDFFF]/.test(child.text![local]!)) fail()
      if (local > 0) out.push(child.type === 'text' ? { ...child, text: child.text!.slice(0, local) } : child)
      out.push(marker); inserted = true
      if (local < length) out.push(child.type === 'text' ? { ...child, text: child.text!.slice(local) } : child)
    } else out.push(child)
    cursor += length
  }
  if (!inserted && offset === cursor) out.push(marker)
  else if (!inserted) fail()
  node.content = out
}
/** 回放只改marker与doc根意图，其他段落属性、文字和marks原样保留。 */
export function replayDocxNotes(doc: DocxPmNode, operations: readonly DocxNoteOperation[], anchors: readonly DocxAnchor[], model: DocxNotesModel, paragraphPlans: DocxNoteOperation[] = []): DocxPmNode {
  projectedDocxNotes(model, operations)
  const result = replayNoteParagraphRuns(doc, paragraphPlans, [...operations], model, anchors), planned = new Set(paragraphPlans.map(plan => plan.blockId)), allocated: Record<DocxNoteKind, string[]> = { footnote: [], endnote: [] }
  for (const op of operations) {
    const kind = op.noteKind as DocxNoteKind
    if (op.kind === 'insertNote') {
      const id = newId(model, allocated[kind], kind); allocated[kind].push(id)
      if (!planned.has(op.blockId)) insertMarker(sourceBlock(result, anchors, op, model), op.offset, kind, id)
    } else if (op.kind === 'deleteNote') {
      const entry = model[`${kind}s`].find(note => note.id === op.noteId)!
      for (const ref of entry.references) {
        if (planned.has(ref.blockId)) continue
        const block = sourceBlock(result, anchors, ref, model)
        const children = block.content?.filter(child => child.type !== 'docNoteRef' || child.attrs?.kind !== kind || String(child.attrs.id) !== entry.id)
        // PM Fragment 自动合并同marks相邻text，回放须采用同样的规范形。
        block.content = children?.reduce<DocxPmNode[]>((out, child) => {
          const previous = out[out.length - 1]
          if (previous?.type === 'text' && child.type === 'text' && same({ ...previous, text: '' }, { ...child, text: '' })) previous.text = (previous.text ?? '') + (child.text ?? '')
          else out.push(child)
          return out
        }, [])
      }
    }
  }
  renumberDocxNotes(result)
  result.attrs = { ...result.attrs, nativeNotesOperations: clone(operations) }
  return result
}
function renumberDocxNotes(result: DocxPmNode) {
  const sequence: Record<DocxNoteKind, Map<string, number>> = { footnote: new Map(), endnote: new Map() }
  const renumber = (node: DocxPmNode) => {
    if (node.type === 'docNoteRef') { const kind = node.attrs?.kind as DocxNoteKind, id = String(node.attrs?.id); if (!kinds.includes(kind)) fail(); const numbers = sequence[kind]; if (!numbers.has(id)) numbers.set(id, numbers.size + 1); node.attrs = { ...node.attrs, num: numbers.get(id) } }
    node.content?.forEach(renumber)
  }
  renumber(result)
}
/** 普通diff先还原注释相关段；真实正文混编以来源切片计划保存。 */
export function normalizeDocxNotes(baseline: DocxPmNode, current: DocxPmNode, anchors: readonly DocxAnchor[], model: DocxNotesModel, includePlainChanges = false) {
  const operations = notesOperationsOf(current), normalized = clone(current), cleanBaseline = clone(baseline)
  projectedDocxNotes(model, operations)
  let expected: DocxPmNode | undefined
  try { expected = replayDocxNotes(baseline, operations, anchors, model) } catch { /* 混编offset绑定当前文档，由最终run计划校验。 */ }
  const paragraphs: DocxNoteOperation[] = []
  const clean = (node: DocxPmNode) => { if (node.type === 'docNoteRef') { node.attrs = { ...node.attrs, num: 1 } }; if (node.type === 'doc') { node.attrs = { ...node.attrs }; delete node.attrs.nativeNotesOperations; if (!Object.keys(node.attrs).length) delete node.attrs }; node.content?.forEach(clean) }
  const affected = new Map<string, Record<string, any>>()
  for (const op of operations) if (op.kind === 'insertNote') affected.set(op.blockId, op)
  else if (op.kind === 'deleteNote') for (const ref of model[`${op.noteKind as DocxNoteKind}s`].find(note => note.id === op.noteId)!.references) affected.set(ref.blockId, ref)
  for (const anchor of anchors) {
    const original = baseline.content?.find(node => node.attrs?.docxIndex === anchor.docxIndex)
    const actual = current.content?.find(node => node.attrs?.docxIndex === anchor.docxIndex)
    if (original && actual && !same(original, actual) && (includePlainChanges || original.content?.some(node => node.type === 'docNoteRef') || actual.content?.some(node => node.type === 'docNoteRef'))) affected.set(anchor.blockId, anchor)
  }
  const layouts: DocxNoteOperation[] = []
  for (const op of affected.values()) {
    const actual = sourceBlock(normalized, anchors, op, model), wanted = expected && sourceBlock(expected, anchors, op, model)
    const source = sourceBlock(cleanBaseline, anchors, op, model)
    const anchor = anchors.find(anchor => anchor.blockId === op.blockId && anchor.expectedObjectSha256 === op.expectedObjectSha256)!
    const layout = noteParagraphLayout(source, actual, anchor, model)
    layouts.push(...layout.operations)
    const a = clone(layout.paragraph), b = wanted && clone(wanted); clean(a); if (b) clean(b)
    if (!b || !same(a, b)) paragraphs.push({ kind: 'patchParagraphRuns', blockId: op.blockId, expectedObjectSha256: op.expectedObjectSha256, runs: compileNoteParagraphRuns(source, layout.paragraph, operations, model, op.blockId, op.expectedObjectSha256) })
    const original = clone(sourceBlock(cleanBaseline, anchors, op, model))
    for (const key of Object.keys(actual)) delete (actual as unknown as Record<string, unknown>)[key]
    Object.assign(actual, original)
  }
  const markers = (doc: DocxPmNode) => { const found: unknown[] = []; const walk = (node: DocxPmNode, blockIndex?: unknown) => { const index = node.attrs?.docxIndex ?? blockIndex; if (node.type === 'docNoteRef') found.push([index, node.attrs?.kind, String(node.attrs?.id), node.attrs?.rawRPr ?? null]); node.content?.forEach(child => walk(child, index)) }; walk(doc); return found }
  if (!same(markers(normalized), markers(cleanBaseline))) fail()
  // 编号是显示投影，普通diff不应把其他段落的重编号当成正文改写。
  clean(normalized); clean(cleanBaseline)
  return { baseline: cleanBaseline, current: normalized, operations: [...layouts, ...paragraphs, ...operations] }
}
/** 新增note的编辑合并到insert；删除新增note取消意图，既有note继续用source hash。 */
export function editDocxNoteOperations(model: DocxNotesModel, operations: readonly DocxNoteOperation[], kind: DocxNoteKind, id: string, text: string | null, context?: { baseline: DocxPmNode; anchors: readonly DocxAnchor[] }): DocxNoteOperation[] {
  const entry = projectedDocxNotes(model, operations).find(entry => entry.kind === kind && entry.id === id)
  if (!entry || text !== null && (!entry.editable || !validText(text))) fail()
  if (entry.pending) {
    if (text !== null) return operations.map((op, index) => index === entry.operationIndex ? { ...clone(op), text } : clone(op))
    const removed = operations[entry.operationIndex]!, result: DocxNoteOperation[] = []
    let position = removed.offset
    operations.forEach((op, index) => {
      if (index === entry.operationIndex) return
      const adjusted = clone(op)
      if (index > entry.operationIndex && op.kind === 'insertNote' && op.blockId === removed.blockId) {
        if (context) {
          const before = replayDocxNotes(context.baseline, operations.slice(0, index), context.anchors, model)
          const block = sourceBlock(before, context.anchors, removed, model)
          position = 0
          let found = false
          for (const child of block.content ?? []) {
            if (child.type === 'docNoteRef' && child.attrs?.kind === kind && String(child.attrs.id) === id) { found = true; break }
            position += child.type === 'text' ? (child.text ?? '').length : 1
          }
          if (!found) fail()
        }
        if (op.offset > position) adjusted.offset--
        if (!context && op.offset <= position) position++
      } else if (!context && index > entry.operationIndex && op.kind === 'deleteNote' && op.expectedReferences.some((ref: DocxNoteReference) => ref.blockId === removed.blockId)) fail()
      result.push(adjusted)
    })
    projectedDocxNotes(model, result)
    return result
  }
  const others = operations.filter(op => !(op.noteKind === kind && op.noteId === id)).map(clone)
  if (text === entry.text && text !== null) return clone(operations) as DocxNoteOperation[]
  return [...others, text === null ? { kind: 'deleteNote', noteKind: kind, noteId: id, expectedNoteSha256: entry.expectedNoteSha256, expectedReferences: clone(entry.references) }
    : { kind: 'updateNote', noteKind: kind, noteId: id, expectedNoteSha256: entry.expectedNoteSha256, text }]
}

/** 注释命令仅改当前marker与意图，当前正文/格式不回滚到来源快照。 */
export function applyDocxNotesIntent(current: DocxPmNode, operations: DocxNoteOperation[], anchors: readonly DocxAnchor[], model: DocxNotesModel,
  removedPending?: { kind: DocxNoteKind; id: string }): DocxPmNode {
  const previous = notesOperationsOf(current), before = projectedDocxNotes(model, previous), after = projectedDocxNotes(model, operations), result = clone(current)
  const oldPending = before.filter(entry => entry.pending && !(removedPending && entry.kind === removedPending.kind && entry.id === removedPending.id))
  const newPending = after.filter(entry => entry.pending)
  const deleted = previous.filter(op => op.kind === 'deleteNote')
  const cleanMarkers = (node: DocxPmNode) => {
    node.content = node.content?.flatMap(child => {
      if (child.type !== 'docNoteRef') { cleanMarkers(child); return [child] }
      const kind = child.attrs?.kind, id = String(child.attrs?.id)
      if (removedPending && kind === removedPending.kind && id === removedPending.id) return []
      if (operations.some(op => op.kind === 'deleteNote' && op.noteKind === kind && op.noteId === id)
        && !deleted.some(op => op.noteKind === kind && op.noteId === id)) return []
      const oldIndex = oldPending.findIndex(entry => entry.kind === kind && entry.id === id)
      if (oldIndex >= 0) {
        const next = newPending[oldIndex]
        if (!next || next.kind !== kind) fail()
        child.attrs = { ...child.attrs, id: next.id }
      }
      return [child]
    })
  }
  cleanMarkers(result)
  if (newPending.length > oldPending.length + 1 || newPending.length < oldPending.length) fail()
  const fresh = newPending[oldPending.length]
  if (fresh) {
    const op = operations[fresh.operationIndex]
    insertMarker(sourceBlock(result, anchors, op, model), op.offset, fresh.kind, fresh.id)
  }
  renumberDocxNotes(result)
  result.attrs = { ...result.attrs, nativeNotesOperations: clone(operations) }
  return result
}
