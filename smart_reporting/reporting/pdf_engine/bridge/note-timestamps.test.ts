import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDocument, PDFName, PDFHexString } from 'pdf-lib'
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
