import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDocument, PDFName, PDFHexString, PDFDict, PDFString } from 'pdf-lib'
import { normalizeAddedNoteDates } from './note-timestamps'
async function fixture(count: number, contents = 'new') {
  const doc = await PDFDocument.create(), page = doc.addPage([300, 400])
  page.node.set(PDFName.of('Annots'), doc.context.obj(Array.from({ length: count }, () => doc.context.register(doc.context.obj({ Type: 'Annot', Subtype: 'Text', Rect: [30, 100, 50, 118], Contents: PDFHexString.fromText(contents) })))))
  return doc.save({ useObjectStreams: false, updateFieldAppearances: false })
}
const note = { pageIndex: 0, rect: [30, 100, 50, 118], contents: 'new', createdMs: 1793970000123 }
test('a missing writer append cannot relabel an identical existing note as new', async () => {
  const base = await fixture(1)
  await assert.rejects(normalizeAddedNoteDates(base, base, [note], [], [0]), /append_count_changed/)
})
test('an unexpected appended annotation payload or missing output page refuses', async () => {
  const base = await fixture(0), wrong = await fixture(1, 'other')
  await assert.rejects(normalizeAddedNoteDates(base, wrong, [note], [], [0]), /append_identity_changed/)
  await assert.rejects(normalizeAddedNoteDates(base, wrong, [note], [], []), /output_page_missing/)
})
test('mixed drawing appends normalize only exact ordered new note slots', async () => {
  const base = await fixture(1)
  const doc = await PDFDocument.load(base)
  const page = doc.getPage(0)
  const annotations = page.node.Annots()!
  const kinds = ['rect', 'note', 'ellipse', 'note', 'line']
  for (const kind of kinds) annotations.push(doc.context.register(doc.context.obj({
    Type: 'Annot', Subtype: kind === 'note' ? 'Text' : 'Square', Rect: note.rect,
    Contents: PDFHexString.fromText('new'),
  })))
  const second = { ...note, createdMs: note.createdMs + 86400000 }
  const result = await normalizeAddedNoteDates(base, await doc.save(), [note, second], [], [0], kinds.map(kind => ({ pageIndex: 0, kind })))
  const saved = await PDFDocument.load(result)
  const values = saved.getPage(0).node.Annots()!
  for (const index of [0, 1, 3, 5]) assert.equal(values.lookup(index, PDFDict).has(PDFName.of('CreationDate')), false)
  for (const [index, value] of [[2, note], [4, second]] as const) {
    assert.equal(values.lookup(index, PDFDict).lookup(PDFName.of('CreationDate'), PDFString).decodeText(), 'D:' + new Date(value.createdMs).toISOString().slice(0, 19).replace(/[-:T]/g, '') + 'Z')
  }
  await assert.rejects(normalizeAddedNoteDates(base, await doc.save(), [note, second], [], [0], [{ pageIndex: 0, kind: 'note' }]), /append_count_changed/)
})
test('real mixed writer preserves existing note and dates two interleaved additions', async () => {
  const { inspectPdf, patchPdfWithReceipt } = await import('./operations')
  const base = await fixture(1), model = await inspectPdf(base), pageId = model.pages[0]!.pageId
  const drawing = { kind: 'addDrawing', pageId, shape: 'rect', rect: [100, 200, 150, 250], color: [1, 0, 0], width: 2 }
  const addition = { kind: 'addTextAnnotation', pageId, text: 'new', rect: note.rect, createdMs: note.createdMs }
  const result = await patchPdfWithReceipt(base, [drawing, addition, drawing, { ...addition, createdMs: note.createdMs + 86400000 }, drawing], model.sourceSha256)
  const doc = await PDFDocument.load(result.bytes), annotations = doc.getPage(0).node.Annots()!
  assert.equal(annotations.size(), 6)
  assert.equal(annotations.lookup(0, PDFDict).has(PDFName.of('CreationDate')), false)
  for (const [index, ms] of [[2, note.createdMs], [4, note.createdMs + 86400000]]) assert.equal(annotations.lookup(index!, PDFDict).lookup(PDFName.of('CreationDate'), PDFString).decodeText(), 'D:' + new Date(ms!).toISOString().slice(0, 19).replace(/[-:T]/g, '') + 'Z')
})
