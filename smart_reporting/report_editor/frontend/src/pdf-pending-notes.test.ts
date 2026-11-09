import { expect, it } from 'vitest'
import { pendingPdfNoteReference, stagePendingPdfNote, validatePendingPdfNote } from './pdf-notes'
import { deletePdfPage, pdfPageState, reversePdfPages } from './pdf-operations'
import { NativeDraft, type NativeOperation } from './native-draft'
const page = { pageId: `sha256:${'c'.repeat(64)}:page:0`, index: 0, rotation: 0, cropBox: { x: 10, y: 20, width: 400, height: 500 }, mediaBox: { x: 0, y: 0, width: 500, height: 600 } }
const other = { ...page, pageId: `sha256:${'c'.repeat(64)}:page:1`, index: 1 }
const note = { kind: 'addTextAnnotation', pageId: page.pageId, rect: [30, 100, 50, 118], text: 'original', color: [.1, .2, .3] }
it('edits only the chosen pending record, preserving location/color/other operations and avoiding an extra operation', () => {
  const operations: NativeOperation[] = [{ kind: 'rotatePage', pageId: page.pageId, delta: 90 }, structuredClone(note), structuredClone(note)]
  const edited = stagePendingPdfNote([page], operations, pendingPdfNoteReference(operations, 2), ' 修改后的正文 ')
  expect(edited).toEqual([operations[0], note, { ...note, text: '修改后的正文' }])
  expect(operations[2].text).toBe('original')
  expect(stagePendingPdfNote([page], edited, pendingPdfNoteReference(edited, 2), null)).toEqual([operations[0], note])
})
it('refuses a stale index even when identical notes shift into that index after deletion', () => {
  const operations: NativeOperation[] = [structuredClone(note), structuredClone(note), structuredClone(note)]
  const reference = pendingPdfNoteReference(operations, 1)
  const next = stagePendingPdfNote([page], operations, pendingPdfNoteReference(operations, 0), null)
  expect(() => stagePendingPdfNote([page], next, reference, null)).toThrow(/草稿已变化/)
  expect(next).toHaveLength(2)
  expect(() => stagePendingPdfNote([page], operations, { ...reference, index: -1 }, null)).toThrow()
  expect(() => stagePendingPdfNote([page], operations, { ...reference, index: 99 }, null)).toThrow()
})
it('keeps edits source-bound through reverse and drops deleted-page notes in one history snapshot', () => {
  const pages = [page, other], reversed = reversePdfPages(pages, [note])
  const edited = stagePendingPdfNote(pages, reversed, pendingPdfNoteReference(reversed, 0), 'after reverse')
  expect(edited[0].pageId).toBe(page.pageId)
  expect(pdfPageState(pages, edited).map(page => page.pageId)).toEqual([other.pageId, page.pageId])
  expect(deletePdfPage(pages, edited, page.pageId).some(op => op.kind === 'addTextAnnotation')).toBe(false)
  const deleted = [note, { kind: 'deletePage', pageId: page.pageId }]
  expect(() => stagePendingPdfNote(pages, deleted, pendingPdfNoteReference(deleted, 0), 'bad')).toThrow(/删除/)
})
it('retains edit/delete/create snapshots through undo redo and reload', () => {
  const values = new Map<string, string>(), storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
  const identity = { documentId: 'pending-note', revision: 1, sourceSha256: 'c'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, storage); draft.setOperations([note]); const created = draft.operations
  draft.setOperations(stagePendingPdfNote([page], draft.operations, pendingPdfNoteReference(draft.operations, 0), 'new')); const edited = draft.operations
  draft.setOperations(stagePendingPdfNote([page], draft.operations, pendingPdfNoteReference(draft.operations, 0), null)); expect(draft.operations).toEqual([])
  draft.undo(); expect(draft.operations).toEqual(edited); draft.undo(); expect(draft.operations).toEqual(created); draft.redo(); expect(draft.operations).toEqual(edited)
  expect(new NativeDraft(identity, storage).operations).toEqual(edited)
})
it('can edit or delete at the 500-operation limit and retains the original batch on invalid input', () => {
  const full: NativeOperation[] = [...Array.from({ length: 499 }, () => ({ kind: 'rotatePage', pageId: page.pageId, delta: 90 })), note]
  const reference = pendingPdfNoteReference(full, 499)
  expect(stagePendingPdfNote([page], full, reference, 'new')).toHaveLength(500)
  expect(stagePendingPdfNote([page], full, reference, null)).toHaveLength(499)
  expect(() => stagePendingPdfNote([page], full, reference, '  ')).toThrow(/正文/)
  expect(() => stagePendingPdfNote([page], full, reference, 'x'.repeat(10001))).toThrow(/正文/)
  expect(full[499].text).toBe('original')
})
it.each([{ text: '' }, { text: 3 }, { color: [2, 0, 0] }, { rect: [1, 2, 3] }, { rect: [400, 100, 405, 118] }, { rect: [30, 20, 50, 30] }, { sourceSha256: '0'.repeat(64) }, { annotationId: 'forged' }])('rejects malformed or stale restored pending notes %j', change => {
  expect(() => validatePendingPdfNote({ ...note, ...change }, page)).toThrow()
  expect(() => pdfPageState([page], [{ ...note, ...change }])).toThrow()
})

it('preserves a fixed creation instant during edit/delete/legacy handling', () => {
  const timed = { ...note, createdMs: 1793970000123 }
  const edited = stagePendingPdfNote([page], [timed], pendingPdfNoteReference([timed], 0), 'updated')
  expect(edited[0].createdMs).toBe(timed.createdMs)
  expect(edited[0].rect).toEqual(note.rect)
  expect(stagePendingPdfNote([page], edited, pendingPdfNoteReference(edited, 0), null)).toEqual([])
  expect(stagePendingPdfNote([page], [note], pendingPdfNoteReference([note], 0), 'legacy')[0]).not.toHaveProperty('createdMs')
})
it.each([-1, .5, 253402300800000, 'invalid', null])('rejects invalid restored creation instant %s', createdMs => {
  expect(() => validatePendingPdfNote({ ...note, createdMs }, page)).toThrow(/创建时间/)
})
