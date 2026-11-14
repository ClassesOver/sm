import { DOCX_FONT_PROPERTIES, DOCX_FONT_DISPLAY } from '../../../reporting/doc_engine/bridge/docx-font-properties'
import { diffArrays } from 'diff'
import { replayDocxOperations, formatRangeChanges, type DocxPmNode } from './docx-operations'
import type { DocxNoteOperation, DocxNotesModel } from './docx-notes'
import { emptyDocxInheritanceNode } from './docx-empty-paragraph'

export type NoteRunPiece = { sourceFrom: number; sourceTo: number; style?: Record<string, unknown> }
  | { text: string; inheritFrom: number; style?: Record<string, unknown> }
  | { noteKind: 'footnote' | 'endnote'; noteId: string; referenceIndex: number }
  | { noteOperationIndex: number }
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const supported = new Set<string>([...DOCX_FONT_PROPERTIES, ...DOCX_FONT_DISPLAY, 'highlight', 'vertAlign', 'color', 'font', 'fontFamily', 'sizeHalfPoints', 'fontSize', 'styleId'])
function opaque(node: DocxPmNode) {
  return (node.marks ?? []).flatMap(mark => {
    if (['bold', 'italic', 'underline', 'strike'].includes(mark.type)) return []
    if (['docTextStyle', 'textStyle'].includes(mark.type)) {
      const attrs = Object.fromEntries(Object.entries(mark.attrs ?? {}).filter(([key, value]) => !supported.has(key) && value != null && value !== false))
      return Object.keys(attrs).length ? [{ type: 'docTextStyle', attrs }] : []
    }
    return [mark]
  })
}
function tokens(node: DocxPmNode) {
  let offset = 0, referenceIndex = 0
  return (node.content ?? []).flatMap(child => {
    if (child.type === 'text' && (!(child.text ?? '').isWellFormed() || /[\uFFFE\uFFFF]/.test(child.text ?? ''))) throw new Error('文字包含无效Unicode字符')
    if (child.type === 'text') return Array.from(child.text ?? '').map(text => {
      const token = { text, node: child, offset, referenceIndex: -1 }; offset += text.length; return token
    })
    if (child.type === 'hardBreak' && !child.attrs?.mathBreak) return [{ text: child.attrs?.pageBreak ? '\f' : child.attrs?.colBreak ? '\v' : child.attrs?.wrapBreak ? '\u001e' : '\n', node: child, offset: offset++, referenceIndex: -1 }]
    if (child.type !== 'docNoteRef') throw new Error('此段落内联对象暂不支持正文与注释混合编辑')
    return [{ text: '\uFFFC', node: child, offset: offset++, referenceIndex: referenceIndex++ }]
  })
}
function delta(before: DocxPmNode, after: DocxPmNode) {
  const paragraph = (node: DocxPmNode): DocxPmNode => ({ type: 'docParagraph', content: [{ ...node, type: 'text', text: 'x' }] })
  return formatRangeChanges(paragraph(before), paragraph(after))[0]?.style
}
/** 源片段仅携带UTF16坐标；不透明run属性由服务端来源继承。 */
export function compileNoteParagraphRuns(baseline: DocxPmNode, current: DocxPmNode, operations: DocxNoteOperation[], model: DocxNotesModel, blockId: string, expectedObjectSha256: string): NoteRunPiece[] {
  if (!same({ ...baseline, content: [] }, { ...current, content: [] })) throw new Error('注释混编暂不支持同时修改段落布局')
  const before = tokens(baseline), after = tokens(current), mapped = new Map<number, number>()
  const equal = (a: typeof before[number], b: typeof before[number]) => a.node.type === b.node.type && a.node.type !== 'docNoteRef'
    && same(a.node.attrs, b.node.attrs) && a.text === b.text && same(opaque(a.node), opaque(b.node))
  let oldAt = 0, newAt = 0
  for (const change of diffArrays(before, after, { comparator: equal })) {
    if (change.added) newAt += change.value.length
    else if (change.removed) oldAt += change.value.length
    else { for (let n = 0; n < change.value.length; n++) mapped.set(newAt++, oldAt++) }
  }
  const sourceRefs = before.filter(token => token.node.type === 'docNoteRef'), usedRefs = new Set<number>(), inserted = new Set<number>()
  const pending: { id: string; index: number; kind: string }[] = [], allocated = { footnote: 0, endnote: 0 }
  operations.forEach((op, index) => {
    if (op.kind !== 'insertNote') return
    const kind = op.noteKind as 'footnote' | 'endnote'
    allocated[kind] ||= Math.max(0, ...model[`${kind}s`].map(note => Number(note.id)))
    pending.push({ kind, id: String(++allocated[kind]), index })
  })
  const trustedReference = (token: typeof before[number]) => {
    const { kind, id } = token.node.attrs ?? {}
    if (kind !== 'footnote' && kind !== 'endnote') return false
    return model[`${kind}s`].find(note => note.id === String(id))?.references.some(ref => ref.blockId === blockId
      && ref.expectedObjectSha256 === expectedObjectSha256 && ref.referenceIndex === token.referenceIndex) ?? false
  }
  const pieces: NoteRunPiece[] = []
  after.forEach((token, index) => {
    if (token.node.type === 'docNoteRef') {
      const { kind, id } = token.node.attrs ?? {}
      const fresh = pending.find(note => note.kind === kind && note.id === String(id))
      if (fresh) {
        const op = operations[fresh.index]
        if (op.blockId !== blockId || inserted.has(fresh.index) || token.node.attrs?.rawRPr != null) throw new Error('新增注释引用身份无效')
        inserted.add(fresh.index); op.offset = token.offset
        pieces.push({ noteOperationIndex: fresh.index }); return
      }
      const source = sourceRefs.find(ref => !usedRefs.has(ref.referenceIndex) && same({ ...ref.node, attrs: { ...ref.node.attrs, num: 1 } }, { ...token.node, attrs: { ...token.node.attrs, num: 1 } }))
      if (!source || operations.some(op => op.kind === 'deleteNote' && op.noteKind === kind && op.noteId === String(id))) throw new Error('既有注释引用身份无效')
      usedRefs.add(source.referenceIndex)
      pieces.push({ noteKind: kind, noteId: String(id), referenceIndex: source.referenceIndex } as NoteRunPiece); return
    }
    const sourceIndex = mapped.get(index)
    const emptyDefault = before.length === 0 ? { node: emptyDocxInheritanceNode(baseline), offset: 0 } : undefined
    const source = sourceIndex === undefined ? before.filter(item => item.node.type === 'text' && same(opaque(item.node), opaque(token.node)))
      .sort((a, b) => Math.abs(a.offset - token.offset) - Math.abs(b.offset - token.offset))[0]
      ?? sourceRefs.filter(item => token.node.type === 'text' && trustedReference(item) && same(opaque(item.node), opaque(token.node)))
        .sort((a, b) => Math.abs(a.offset - token.offset) - Math.abs(b.offset - token.offset))[0] ?? (emptyDefault && same(opaque(emptyDefault.node), opaque(token.node)) ? emptyDefault : undefined) : before[sourceIndex]
    if (!source) throw new Error('新增文字无法安全继承来源格式')
    const style = delta(source.node, token.node), extra = style ? { style } : {}
    const piece: NoteRunPiece = sourceIndex === undefined ? { text: token.text, inheritFrom: source.offset, ...extra }
      : { sourceFrom: source.offset, sourceTo: source.offset + token.text.length, ...extra }
    const previous = pieces.at(-1)
    if (previous && token.node.type === 'text' && 'sourceTo' in previous && 'sourceFrom' in piece && previous.sourceTo === piece.sourceFrom && same(previous.style, piece.style)) previous.sourceTo = piece.sourceTo
    else if (previous && 'text' in previous && 'text' in piece && previous.inheritFrom === piece.inheritFrom && same(previous.style, piece.style)) previous.text += piece.text
    else pieces.push(piece)
  })
  for (const source of sourceRefs) if (!usedRefs.has(source.referenceIndex) && !operations.some(op => op.kind === 'deleteNote' && op.noteKind === source.node.attrs?.kind && op.noteId === String(source.node.attrs?.id))) throw new Error('删除注释引用需要匹配的删除操作')
  for (const note of pending) if (operations[note.index].blockId === blockId && !inserted.has(note.index)) throw new Error('新增注释缺少正文引用')
  let lastSourceTo = 0
  for (const piece of pieces) {
    if ('sourceFrom' in piece) { if (piece.sourceFrom < lastSourceTo) throw new Error('来源文字片段顺序无效'); lastSourceTo = piece.sourceTo }
    else if ('referenceIndex' in piece) {
      const source = sourceRefs.find(ref => ref.referenceIndex === piece.referenceIndex)!
      if (source.offset < lastSourceTo) throw new Error('既有注释引用不能移出来源顺序')
      lastSourceTo = source.offset + 1
    }
  }
  return pieces
}

/** 草稿按来源切片恢复，再用相同编译器验证等价，禁止持久化意图伪造marker。 */
export function replayNoteParagraphRuns(doc: DocxPmNode, plans: DocxNoteOperation[], operations: DocxNoteOperation[], model: DocxNotesModel,
  anchors: readonly { docxIndex: number; blockId: string; expectedObjectSha256: string; editable: boolean }[]): DocxPmNode {
  const result = structuredClone(doc), pending = new Map<number, { kind: string; id: string }>(), next = { footnote: Math.max(0, ...model.footnotes.map(note => Number(note.id))), endnote: Math.max(0, ...model.endnotes.map(note => Number(note.id))) }
  operations.forEach((op, index) => { if (op.kind === 'insertNote') { const kind = op.noteKind as 'footnote' | 'endnote'; pending.set(index, { kind, id: String(++next[kind]) }) } })
  const used = new Set<string>()
  for (const plan of plans) {
    const anchor = anchors.find(anchor => anchor.blockId === plan.blockId && anchor.expectedObjectSha256 === plan.expectedObjectSha256)
    const eligible = model.referenceBlocks?.find(block => block.blockId === anchor?.blockId && block.expectedObjectSha256 === anchor.expectedObjectSha256)
    const source = doc.content?.find(node => node.attrs?.docxIndex === anchor?.docxIndex), target = result.content?.find(node => node.attrs?.docxIndex === anchor?.docxIndex)
    if (!anchor || !(eligible?.editable ?? anchor.editable) || !source || !target || used.has(anchor.blockId) || !Array.isArray(plan.runs)
      || Object.keys(plan).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'runs'].includes(key))) throw new Error('正文注释草稿来源身份无效')
    used.add(anchor.blockId)
    const original = tokens(source), output: DocxPmNode[] = []
    for (const piece of plan.runs as NoteRunPiece[]) {
      let children: DocxPmNode[]
      if ('sourceFrom' in piece) children = original.filter(token => token.offset >= piece.sourceFrom && token.offset < piece.sourceTo).map(token => token.node.type === 'text' ? { ...structuredClone(token.node), text: token.text } : structuredClone(token.node))
      else if ('text' in piece) {
        const token = original.find(token => token.offset === piece.inheritFrom && ['text', 'docNoteRef'].includes(token.node.type))
          ?? (original.length === 0 && piece.inheritFrom === 0 ? { node: emptyDocxInheritanceNode(source) } : undefined)
        if (!token || !piece.text) throw new Error('正文注释草稿继承位置无效')
        children = [token.node.type === 'docNoteRef' ? { type: 'text', text: piece.text, marks: structuredClone(token.node.marks) } : { ...structuredClone(token.node), text: piece.text }]
      } else if ('referenceIndex' in piece) {
        const token = original.find(token => token.referenceIndex === piece.referenceIndex && token.node.type === 'docNoteRef')
        if (!token || token.node.attrs?.kind !== piece.noteKind || String(token.node.attrs?.id) !== piece.noteId) throw new Error('正文注释草稿引用身份无效')
        children = [structuredClone(token.node)]
      } else {
        const note = pending.get(piece.noteOperationIndex)
        if (!note) throw new Error('正文注释草稿新增引用无效')
        children = [{ type: 'docNoteRef', attrs: { ...note, num: 1, rawRPr: null } }]
      }
      for (const child of children) {
        if ('style' in piece && piece.style) {
          const styledChild = child.type === 'hardBreak' ? { ...child, type: 'text', text: 'x' } : child
          const tiny: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [styledChild] }] }
          const length = styledChild.text?.length ?? 0
          if (!length) throw new Error('注释marker不能通过正文格式意图修改')
          const formatted = replayDocxOperations(tiny, [{ kind: 'formatRange', blockId: 'piece', expectedObjectSha256: 'piece', from: 0, to: length, style: piece.style }], [{ docxIndex: 0, blockId: 'piece', expectedObjectSha256: 'piece', editable: true }]).content![0].content!
          output.push(...(child.type === 'hardBreak' ? formatted.map(part => ({ ...child, marks: part.marks })) : formatted))
        } else output.push(child)
      }
    }
    target.content = output
    const adjusted = structuredClone(operations)
    const canonical = compileNoteParagraphRuns(source, target, adjusted, model, anchor.blockId, anchor.expectedObjectSha256)
    if (!same(adjusted, operations) || !same(canonical, plan.runs)) throw new Error('正文注释草稿run计划与来源不一致')
  }
  return result
}
