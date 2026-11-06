import { expect, it } from 'vitest'
import { stagePdfNote } from './pdf-notes'
import { pdfPageState } from './pdf-operations'
import { NativeDraft } from './native-draft'
const note = { annotationId: 'a'.repeat(64), expectedAnnotationSha256: 'b'.repeat(64), contents: 'original', editable: true, removable: true, removalReason: null }
const page = { pageId: `sha256:${'c'.repeat(64)}:page:0`, index: 0, rotation: 0, cropBox: { x: 0, y: 0, width: 400, height: 500 }, mediaBox: { x: 0, y: 0, width: 400, height: 500 }, notesReadSafe: true, notes: [note] }
const when = '2026-11-06T13:00:00Z'
it('replaces successive note edits, drops restored contents and replaces edit with delete without mutating source', () => {
  const first = stagePdfNote([page], [], page.pageId, note.annotationId, ' first ', when)
  const second = stagePdfNote([page], first, page.pageId, note.annotationId, 'second', when)
  expect(second).toHaveLength(1); expect(second[0].contents).toBe('second')
  expect(stagePdfNote([page], second, page.pageId, note.annotationId, 'original', when)).toEqual([])
  const removed = stagePdfNote([page], second, page.pageId, note.annotationId, null)
  expect(removed[0].kind).toBe('removeNote'); expect(pdfPageState([page], removed)[0].notes).toEqual([])
  expect(pdfPageState([page], first)[0].notes?.[0].contents).toBe('first'); expect(page.notes[0].contents).toBe('original')
})
it('preserves full note snapshots through undo redo and reload', () => {
  const values = new Map<string, string>(), storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
  const identity = { documentId: 'note', revision: 1, sourceSha256: 'c'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, storage)
  draft.setOperations(stagePdfNote([page], [], page.pageId, note.annotationId, 'new', when)); const edited = draft.operations
  draft.setOperations(stagePdfNote([page], draft.operations, page.pageId, note.annotationId, null)); const deleted = draft.operations
  draft.undo(); expect(draft.operations).toEqual(edited); draft.redo(); expect(draft.operations).toEqual(deleted)
  expect(new NativeDraft(identity, storage).operations).toEqual(deleted)
})
it('refuses readonly/deleted source and budget overflow atomically while allowing replacement at capacity', () => {
  expect(() => stagePdfNote([{ ...page, notes: [{ ...note, editable: false, removalReason: '关联回复' }] }], [], page.pageId, note.annotationId, 'new', when)).toThrow(/关联回复/)
  expect(() => stagePdfNote([page], [{ kind: 'deletePage', pageId: page.pageId }], page.pageId, note.annotationId, 'new', when)).toThrow(/删除/)
  const full = Array.from({ length: 500 }, () => ({ kind: 'rotatePage', pageId: page.pageId, delta: 90 }))
  expect(() => stagePdfNote([page], full, page.pageId, note.annotationId, 'new', when)).toThrow(/500/); expect(full).toHaveLength(500)
  const edit = stagePdfNote([page], [], page.pageId, note.annotationId, 'new', when)
  expect(stagePdfNote([page], [...full.slice(1), ...edit], page.pageId, note.annotationId, 'again', when)).toHaveLength(500)
})
it('validates restored notes against exact identity, timestamp, extra fields and duplicate mutations', () => {
  const operation = stagePdfNote([page], [], page.pageId, note.annotationId, 'new', when)[0]
  for (const ops of [[operation, operation], [{ ...operation, annotationId: 'f'.repeat(64) }], [{ ...operation, expectedAnnotationSha256: 'f'.repeat(64) }], [{ ...operation, modifiedAt: '2026-02-30T13:00:00Z' }], [{ ...operation, contents: '   ' }], [{ ...operation, sourceSha256: '0'.repeat(64) }], [{ ...operation, rect: [1, 2, 3, 4] }]]) expect(() => pdfPageState([page], ops)).toThrow()
})
