import { expect, it } from 'vitest'
import { NativeDraft, type NativeOperation } from './native-draft'
import { PDF_PAPER_SIZES, setPdfPageSize, validatePdfSizeOperations, pdfPageState, cropPdfPage } from './pdf-operations'

it('retains pinned source paper labels, order and exact point sizes', () => {
  expect(PDF_PAPER_SIZES.map(p => [p.label, p.width, p.height])).toEqual([['A3', 842, 1191], ['A4', 595, 842], ['A5', 420, 595], ['Letter', 612, 792], ['Legal', 612, 1008]])
})
it('keeps a single final paper transform while preserving source coordinate operations', () => {
  const operations = [{ kind: 'rotatePage', pageId: 'source:0', delta: 90 }]
  const next = setPdfPageSize(operations, 'A4')
  expect(next).toEqual([...operations, { kind: 'setPageSize', preset: 'A4' }])
  expect(setPdfPageSize(next, 'A5')).toEqual([...operations, { kind: 'setPageSize', preset: 'A5' }])
  expect(setPdfPageSize(next, 'A4')).toEqual(next)
  expect(operations).toHaveLength(1)
})
it.each(['cropPage', 'replaceText'])('rejects paper mixing with %s without rewriting the draft', kind => {
  const before: NativeOperation[] = [{ kind, pageId: 'source:0' }]
  expect(() => setPdfPageSize(before, 'A4')).toThrow(/混用/)
  expect(before).toEqual([{ kind, pageId: 'source:0' }])
})
it('validates restored paper records, duplicate transforms, and operation budget', () => {
  expect(() => validatePdfSizeOperations([{ kind: 'setPageSize', preset: 'A6' }])).toThrow()
  expect(() => validatePdfSizeOperations([{ kind: 'setPageSize', preset: 'A4' }, { kind: 'setPageSize', preset: 'A5' }])).toThrow()
  expect(() => setPdfPageSize(Array.from({ length: 500 }, () => ({ kind: 'setFormValue', name: 'a' })), 'A4')).toThrow(/500/)
  expect(setPdfPageSize(Array.from({ length: 499 }, () => ({ kind: 'setFormValue', name: 'a' })), 'A4')).toHaveLength(500)
})
it('retains original source geometry for editing until the actual output preview is loaded', () => {
  const pages = [{ pageId: 'source:0', index: 0, rotation: 0, cropBox: { x: 10, y: 20, width: 300, height: 400 }, mediaBox: { x: 0, y: 0, width: 400, height: 500 } }]
  const operations = setPdfPageSize([], 'A4')
  expect(pdfPageState(pages, operations)).toEqual(pages)
  expect(() => cropPdfPage(pages, operations, 'source:0', [20, 30, 300, 400])).toThrow(/保存/)
})
it('restores preset changes as independent undo steps across reload', () => {
  const values = new Map<string, string>()
  const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
  const identity = { documentId: 'paper', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'test', companyId: 'test', userId: 'test', threadId: 'test' } }
  const draft = new NativeDraft(identity, storage)
  draft.setOperations(setPdfPageSize([], 'A4')); draft.setOperations(setPdfPageSize(draft.operations, 'A5'))
  draft.undo(); expect(draft.operations).toEqual([{ kind: 'setPageSize', preset: 'A4' }])
  draft.redo(); expect(new NativeDraft(identity, storage).operations).toEqual([{ kind: 'setPageSize', preset: 'A5' }])
})
