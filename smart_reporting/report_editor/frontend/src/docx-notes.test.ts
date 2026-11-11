import { expect, it } from 'vitest'
import { createDocxNotesPlanner } from '../../../reporting/doc_engine/bridge/docx-notes'

const head = '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
const separator = '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
const simple = '<w:footnote w:id="1"><w:p><w:r><w:footnoteRef/></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>Original</w:t></w:r></w:p></w:footnote>'
const complex = '<w:footnote w:id="2"><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Keep table</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:footnote>'
const source = () => ({ sourceSha256: 'source', footnotesXml: head + separator + simple + complex + '</w:footnotes>', endnotesXml: null,
  blocks: [{ blockId: 'body', expectedObjectSha256: 'body-sha', editable: true, runs: [{ text: 'Ab😀cd', bold: true }, { text: '1', noteRef: { kind: 'footnote' as const, id: '1' } }] }] })

it('anchors notes and references while preserving separator and unchanged complex entry bytes', () => {
  const planner = createDocxNotesPlanner(source()), note = planner.model.footnotes[0]!
  expect(note.references).toEqual([{ blockId: 'body', expectedObjectSha256: 'body-sha', referenceIndex: 0 }])
  expect(planner.model.footnotes[1]).toMatchObject({ editable: false, text: 'Keep table' })
  const result = planner.plan([{ kind: 'updateNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: note.expectedNoteSha256, text: 'Changed' }])
  expect(result.parts.footnote).toContain(separator)
  expect(result.parts.footnote).toContain(complex)
  expect(result.parts.footnote).toContain('<w:b/>')
  expect(result.parts.footnote).toContain('Changed')
  expect(result.blocks.size).toBe(0)
  expect(result.endnotes).toBeUndefined()
})

it('inserts a server-allocated note and a real body marker without losing surrounding formatting', () => {
  const planner = createDocxNotesPlanner(source())
  const result = planner.plan([{ kind: 'insertNote', noteKind: 'endnote', blockId: 'body', expectedObjectSha256: 'body-sha', offset: 4, text: 'New endnote' }])
  expect(result.endnotes).toEqual([{ id: '1', text: 'New endnote' }])
  expect(result.blocks.get('body')).toEqual([{ text: 'Ab😀', bold: true }, { text: '1', noteRef: { kind: 'endnote', id: '1' } }, { text: 'cd', bold: true }, { text: '1', noteRef: { kind: 'footnote', id: '1' } }])
  expect(result.parts.endnote).toContain('continuationSeparator')
})

it('deletes exactly the anchored note and all matching references while retaining unrelated entries', () => {
  const planner = createDocxNotesPlanner(source()), note = planner.model.footnotes[0]!
  const result = planner.plan([{ kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: note.expectedNoteSha256, expectedReferences: note.references }])
  expect(result.footnotes?.map(note => note.id)).toEqual(['2'])
  expect(result.blocks.get('body')).toEqual([{ text: 'Ab😀cd', bold: true }])
  expect(result.parts.footnote).toContain(complex)
  expect(result.parts.footnote).toContain(separator)
})

it.each(['hash', 'references', 'complex', 'surrogate', 'foreign-block', 'extra-field', 'duplicate'])('rejects %s before producing partial changes', fault => {
  const planner = createDocxNotesPlanner(source()), note = planner.model.footnotes[0]!
  const update = { kind: 'updateNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: note.expectedNoteSha256, text: 'Changed' }
  const operation = fault === 'references' ? { kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: note.expectedNoteSha256, expectedReferences: [] }
    : fault === 'surrogate' || fault === 'foreign-block' ? { kind: 'insertNote', noteKind: 'footnote', blockId: fault === 'foreign-block' ? 'foreign' : 'body', expectedObjectSha256: 'body-sha', offset: 3, text: 'New' }
    : fault === 'complex' ? { ...update, noteId: '2', expectedNoteSha256: planner.model.footnotes[1]!.expectedNoteSha256 }
    : fault === 'hash' ? { ...update, expectedNoteSha256: 'foreign' }
    : fault === 'extra-field' ? { ...update, xml: '<x/>' } : update
  expect(() => planner.plan(fault === 'duplicate' ? [operation, operation] : [operation])).toThrow(/docx_note_/)
  expect(planner.plan([]).parts).toEqual({})
})

import { editDocxNoteOperations, normalizeDocxNotes, projectedDocxNotes, replayDocxNotes, type DocxNotesModel } from './docx-notes'
import type { DocxPmNode } from './docx-operations'
const anchors = [{ docxIndex: 0, blockId: 'body', expectedObjectSha256: 'body-sha', editable: false }]
const pmSource = (): DocxPmNode => ({ type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'Ab😀cd', marks: [{ type: 'bold' }] }, { type: 'docNoteRef', attrs: { kind: 'footnote', id: '1', num: 1, rawRPr: null } }] }] })
const modelOf = (): DocxNotesModel => ({ ...createDocxNotesPlanner(source()).model, referenceBlocks: [{ blockId: 'body', expectedObjectSha256: 'body-sha', editable: true }] })
const insert = (offset: number, noteKind = 'footnote') => ({ kind: 'insertNote', noteKind, blockId: 'body', expectedObjectSha256: 'body-sha', offset, text: 'New' })

it('uses notes-only eligibility and normalizes marker edits without ordinary body rewrite', () => {
  const model = modelOf(), baseline = pmSource(), current = replayDocxNotes(baseline, [insert(4)], anchors, model)
  expect(current.content![0]!.content!.filter(node => node.type === 'docNoteRef').map(node => node.attrs?.id)).toEqual(['3', '1'])
  const normalized = normalizeDocxNotes(baseline, current, anchors, model)
  expect(normalized.current).toEqual(normalized.baseline)
  expect(normalized.operations).toEqual([insert(4)])
  current.content![0]!.content![0]!.text = 'tampered'
  expect(normalizeDocxNotes(baseline, current, anchors, model).operations[0]).toMatchObject({ kind: 'patchParagraphRuns', blockId: 'body' })
})

it('cancels pending insert and rebases subsequent same-block offsets including source deletion', () => {
  const model = modelOf(), baseline = pmSource(), entry = model.footnotes[0]!
  const remove = { kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: entry.expectedNoteSha256, expectedReferences: entry.references }
  const operations = [insert(7), remove, insert(7, 'endnote')]
  const changed = editDocxNoteOperations(model, operations, 'footnote', '3', null, { baseline, anchors })
  expect(changed).toEqual([remove, insert(6, 'endnote')])
  const current = replayDocxNotes(baseline, changed, anchors, model)
  expect(current.content![0]!.content!.map(node => node.type === 'text' ? node.text : `${node.attrs?.kind}:${node.attrs?.id}`).join('')).toBe('Ab😀cdendnote:1')
})

it('restores a formerly empty paragraph and rejects marker changes without operations', () => {
  const model = modelOf(), empty: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  const current = replayDocxNotes(empty, [insert(0)], anchors, model)
  const normalized = normalizeDocxNotes(empty, current, anchors, model)
  expect(normalized.current).toEqual(normalized.baseline)
  const forged = pmSource(); forged.content![0]!.content![1]!.attrs!.id = 'forged'
  expect(() => normalizeDocxNotes(pmSource(), forged, anchors, model)).toThrow()
})

it('does not expose mutable server source identities through its inspect model', () => {
  const planner = createDocxNotesPlanner(source()), hash = planner.model.footnotes[0]!.expectedNoteSha256
  planner.model.footnotes[0]!.expectedNoteSha256 = 'forged'
  expect(() => planner.plan([{ kind: 'updateNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: 'forged', text: 'Oops' }])).toThrow()
  expect(planner.plan([{ kind: 'updateNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: hash, text: 'Valid' }]).footnotes?.[0]?.text).toBe('Valid')
})

it('combines multiple note insertions and deletion in one block using atomic marker width', () => {
  const planner = createDocxNotesPlanner(source()), note = planner.model.footnotes[0]!
  const result = planner.plan([insert(6), { kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: note.expectedNoteSha256, expectedReferences: note.references }, insert(7, 'endnote')])
  expect(result.blocks.get('body')?.map(run => run.noteRef ? `${run.noteRef.kind}:${run.noteRef.id}` : run.text)).toEqual(['Ab😀cd', 'footnote:3', 'endnote:1'])
  expect(projectedDocxNotes(modelOf(), [insert(4)]).find(note => note.pending)?.id).toBe('3')
})

it('refuses unknown note-part children instead of silently removing them during update', () => {
  const original = source()
  original.footnotesXml = original.footnotesXml.replace('</w:footnotes>', '<w:customData w:val="keep"/></w:footnotes>')
  expect(() => createDocxNotesPlanner(original)).toThrow(/part_unsupported/)
})

it('leaves tab-containing note text read-only because text projection does not encode tabs', () => {
  const original = source()
  original.footnotesXml = original.footnotesXml.replace('<w:t>Original</w:t>', '<w:t>Original</w:t><w:tab/>')
  expect(createDocxNotesPlanner(original).model.footnotes[0]?.editable).toBe(false)
})

it('rejects dangling body markers rather than allocating an id that rebinds them', () => {
  const original = source()
  original.blocks[0]!.runs.push({ text: '5', noteRef: { kind: 'footnote', id: '5' } })
  expect(() => createDocxNotesPlanner(original)).toThrow(/reference_identity_invalid/)
})

it('keeps native hard-break atom offsets when inserting a reference', () => {
  const baseline: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'A' }, { type: 'hardBreak' }, { type: 'text', text: 'B' }] }] }
  const current = replayDocxNotes(baseline, [insert(2)], anchors, modelOf())
  expect(current.content![0]!.content!.map(node => node.type)).toEqual(['text', 'hardBreak', 'docNoteRef', 'text'])
})

it('normalizes source-marker deletion after native ProseMirror merges the surrounding text', async () => {
  const { Editor, Extension } = await import('@tiptap/core')
  const { editorExtensions } = await import('./vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions')
  const Notes = Extension.create({ name: 'testNotesIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
  const editor = new Editor({ extensions: [...editorExtensions, Notes], content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
    { type: 'text', text: '第', marks: [{ type: 'bold' }] }, { type: 'docNoteRef', attrs: { kind: 'footnote', id: '1', num: 1, rawRPr: null } }, { type: 'text', text: '二段正文', marks: [{ type: 'bold' }] },
  ] }] } })
  try {
    const baseline = editor.getJSON(), model = modelOf(), entry = model.footnotes[0]!
    const operations = [{ kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: entry.expectedNoteSha256, expectedReferences: entry.references }]
    editor.commands.setContent(replayDocxNotes(baseline, operations, anchors, model))
    editor.view.dispatch(editor.state.tr.setDocAttribute('nativeNotesOperations', operations))
    expect(editor.getJSON().content![0]!.content).toHaveLength(1)
    const normalized = normalizeDocxNotes(baseline, editor.getJSON(), anchors, model)
    expect(normalized.current).toEqual(normalized.baseline)
  } finally { editor.destroy() }
}, 20000)
