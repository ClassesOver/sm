/** Native deterministic-date adapter for pinned save-pdf.addDrawing(note).
 * The pinned writer appends one note annotation per drawing after markups.
 * Verify exact counts and suffix payload before changing only the newly added dates.
 */
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFNumber, PDFRef, PDFString } from 'pdf-lib'
export interface AddedNoteDate { pageIndex: number; contents: string; rect: number[]; createdMs?: number; replyToRef?: string; localId?: string; replyToLocalId?: string }
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
  const originalRefs = new Set(base.getPages().flatMap(page => page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray().filter(raw=>raw instanceof PDFRef).map(String) ?? []))
  const addedRefs = new Set<string>(), localRoots = new Map<string,{ref:string;pageIndex:number}>()
  for (const [sourceIndex,list] of byPage) {
    const annotations=output.getPage(outputOrder.indexOf(sourceIndex)).node.lookup(PDFName.of('Annots'),PDFArray),count=expectedCounts.get(sourceIndex)!
    for (const [offset,note] of list.entries()) {
      const raw=annotations.get(count-list.length+offset)
      if (!(raw instanceof PDFRef)) throw Error('pdf_added_note_append_identity_changed')
      if (note.localId!==undefined || note.replyToLocalId!==undefined) {
        if (originalRefs.has(String(raw)) || addedRefs.has(String(raw))) throw Error('pdf_added_note_reference_reused')
        addedRefs.add(String(raw))
      }
      if (note.localId!==undefined) {
        if (localRoots.has(note.localId)) throw Error('pdf_local_reply_duplicate_root')
        const dict=annotations.lookup(count-list.length+offset,PDFDict)
        if (dict.has(PDFName.of('IRT')) || dict.has(PDFName.of('RT'))) throw Error('pdf_local_reply_root_changed')
        localRoots.set(note.localId,{ref:String(raw),pageIndex:sourceIndex})
      }
    }
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
      const localParent=note.replyToLocalId===undefined?undefined:localRoots.get(note.replyToLocalId)
      if (note.replyToLocalId!==undefined && (!localParent || localParent.pageIndex!==sourceIndex)) throw Error('pdf_local_reply_parent_missing')
      const expectedParent=localParent?.ref ?? note.replyToRef
      if (expectedParent !== undefined && (String(annotation.get(PDFName.of('IRT'))) !== expectedParent || String(annotation.get(PDFName.of('RT'))) !== '/R')) throw new Error('pdf_reply_parent_reference_changed')
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
