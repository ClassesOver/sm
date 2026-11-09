/** Native deterministic-date adapter for pinned save-pdf.addDrawing(note).
 * The pinned writer appends one note annotation per drawing after markups.
 * Verify exact counts and suffix payload before changing only the newly added dates.
 */
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFNumber, PDFRef, PDFString } from 'pdf-lib'
export interface AddedNoteDate { pageIndex: number; contents: string; rect: number[]; createdMs?: number; replyToRef?: string }
export async function normalizeAddedNoteDates(baseBytes: Uint8Array, outputBytes: Uint8Array, notes: AddedNoteDate[], markupPages: number[], outputOrder: number[]) {
  if (!notes.length) return outputBytes
  const base = await PDFDocument.load(baseBytes, { updateMetadata: false })
  const output = await PDFDocument.load(outputBytes, { updateMetadata: false })
  const byPage = new Map<number, AddedNoteDate[]>()
  for (const note of notes) byPage.set(note.pageIndex, [...(byPage.get(note.pageIndex) ?? []), note])
  if ([...byPage.keys()].some(index => !outputOrder.includes(index))) throw new Error('pdf_added_note_output_page_missing')
  const expectedCounts = new Map<number, number>()
  // Also inspect untouched survivors: a shared indirect Annots array must not
  // append a new note to an unrelated page as a collateral side effect.
  for (const [outputIndex, sourceIndex] of outputOrder.entries()) {
    const original = base.getPage(sourceIndex).node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    const expected = (original?.size() ?? 0) + markupPages.filter(index => index === sourceIndex).length + (byPage.get(sourceIndex)?.length ?? 0)
    const actual = output.getPage(outputIndex).node.lookupMaybe(PDFName.of('Annots'), PDFArray)?.size() ?? 0
    if (actual !== expected) throw new Error('pdf_added_note_append_count_changed')
    expectedCounts.set(sourceIndex, expected)
  }
  for (const [sourceIndex, list] of byPage) {
    const outputIndex = outputOrder.indexOf(sourceIndex)
    if (outputIndex < 0) throw new Error('pdf_added_note_output_page_missing')
    const annotations = output.getPage(outputIndex).node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    const expected = expectedCounts.get(sourceIndex)!
    if (!annotations || annotations.size() !== expected) throw new Error('pdf_added_note_append_count_changed')
    for (const [offset, note] of list.entries()) {
      const raw = annotations.get(expected - list.length + offset)
      if (!(raw instanceof PDFRef)) throw new Error('pdf_added_note_append_identity_changed')
      const annotation = annotations.lookup(expected - list.length + offset, PDFDict)
      const contents = annotation.lookup(PDFName.of('Contents'))
      const rect = annotation.lookupMaybe(PDFName.of('Rect'), PDFArray)?.asArray()
      if (String(annotation.get(PDFName.of('Subtype'))) !== '/Text' || !(contents instanceof PDFString || contents instanceof PDFHexString) || contents.decodeText() !== note.contents || !rect || rect.length !== 4 || rect.some((value, i) => !(value instanceof PDFNumber) || value.asNumber() !== note.rect[i])) throw new Error('pdf_added_note_append_identity_changed')
      if (note.replyToRef !== undefined && (String(annotation.get(PDFName.of('IRT'))) !== note.replyToRef || String(annotation.get(PDFName.of('RT'))) !== '/R')) throw new Error('pdf_reply_parent_reference_changed')
      if (note.createdMs === undefined) {
        // Legacy drafts have no trustworthy creation instant. Keep optional dates unknown.
        annotation.delete(PDFName.of('CreationDate')); annotation.delete(PDFName.of('M'))
      } else {
        const when = 'D:' + new Date(note.createdMs).toISOString().slice(0, 19).replace(/[-:T]/g, '') + 'Z'
        annotation.set(PDFName.of('CreationDate'), PDFString.of(when)); annotation.set(PDFName.of('M'), PDFString.of(when))
      }
    }
  }
  return output.save({ useObjectStreams: false, updateFieldAppearances: false })
}
