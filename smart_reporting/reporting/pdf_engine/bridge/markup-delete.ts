/** Native strict adapter for the pinned pre-save annotation-delete stage.
 * No geometry fallback: resolve immutable source ID/dictionary hash, unlink only its page slot.
 */
import { createHash } from 'node:crypto'
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFObject, PDFRef } from 'pdf-lib'
const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex')
const types = new Set(['/Highlight', '/Underline', '/Squiggly', '/StrikeOut'])
export function markupSourceId(sourceSha256: string, pageIndex: number, index: number) {
  return hash(`${sourceSha256}:page:${pageIndex}:annotation:${index}`)
}
export function markupDictionaryHash(annotation: PDFDict) { return hash(annotation.toString()) }
export function markupRemovalLinks(document: PDFDocument, protectedSource: boolean) {
  const linked = new Set<string>()
  try {
    for (const page of document.getPages()) {
      const annotations = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
      if (!annotations) continue
      for (const entry of annotations.asArray()) {
        const annotation = document.context.lookup(entry, PDFDict)
        for (const key of ['IRT', 'Parent', 'Popup']) {
          const reference = annotation.get(PDFName.of(key))
          if (reference instanceof PDFRef) linked.add(reference.toString())
        }
      }
    }
  } catch { protectedSource = true }
  return { linked, protectedSource }
}
export function markupRemovalIdentity(sourceSha256: string, pageIndex: number, index: number, raw: PDFObject, annotation: PDFDict, links: ReturnType<typeof markupRemovalLinks>) {
  const reason = links.protectedSource ? '签名、动态表单或未完整读取的引用结构暂不支持标注移除'
    : !(raw instanceof PDFRef) ? '直接嵌入的标注对象暂不支持移除'
    : ['IRT', 'Parent', 'Popup', 'StructParent'].some(key => annotation.has(PDFName.of(key))) || links.linked.has(raw.toString()) ? '此标注有关联回复、弹窗或结构信息，暂不支持移除' : null
  return { annotationId: markupSourceId(sourceSha256, pageIndex, index), expectedAnnotationSha256: markupDictionaryHash(annotation), removable: reason === null, removalReason: reason }
}
export interface MarkupRemoval { pageIndex: number; annotationId: string; expectedAnnotationSha256: string }
export async function removeSourceMarkups(content: Uint8Array, sourceSha256: string, removals: MarkupRemoval[]) {
  if (!removals.length) return content
  if (hash(content) !== sourceSha256) throw new Error('pdf_markup_source_changed')
  const document = await PDFDocument.load(content, { updateMetadata: false })
  const byPage = new Map<number, MarkupRemoval[]>()
  for (const removal of removals) byPage.set(removal.pageIndex, [...(byPage.get(removal.pageIndex) ?? []), removal])
  // All caller identities have already been validated before any stage writes bytes.
  for (const [pageIndex, list] of byPage) {
    const page = document.getPage(pageIndex), annotations = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    if (!annotations) throw new Error('pdf_markup_source_changed')
    const indices = new Map(annotations.asArray().map((_, index) => [markupSourceId(sourceSha256, pageIndex, index), index]))
    const removed = new Set<number>()
    for (const removal of list) {
      const index = indices.get(removal.annotationId)
      if (index === undefined || removed.has(index)) throw new Error('pdf_markup_identity_invalid')
      const annotation = annotations.lookup(index, PDFDict)
      if (!types.has(String(annotation.get(PDFName.of('Subtype')))) || markupDictionaryHash(annotation) !== removal.expectedAnnotationSha256) throw new Error('pdf_markup_identity_invalid')
      removed.add(index)
    }
    // Copy this page's array: a source can share an indirect Annots array with another page.
    page.node.set(PDFName.of('Annots'), document.context.obj(annotations.asArray().filter((_, index) => !removed.has(index))))
  }
  return document.save({ useObjectStreams: false, updateFieldAppearances: false })
}
