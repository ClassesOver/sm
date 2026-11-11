/** Preserve visible annotation appearances before the pinned N-up page embedder. */
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber, PDFRawStream, PDFRef } from 'pdf-lib'
import { chainPdfium, loadPdfium, saveDoc, withDocument } from '../src/main/text-edit'
import { replyReferences } from './note-replies'

export function assertRedactionAnnotationSafety(document: PDFDocument, regions: { pageIndex: number; rect: readonly number[] }[]) {
  const counts = replyReferences(document, false)
  if (!counts) throw new Error('涂黑涉及关联批注或共享外观，无法保证信息完全移除' )
  for (const region of regions) {
    const annots = document.getPage(region.pageIndex).node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    for (let index = 0; index < (annots?.size() ?? 0); index++) {
      const raw = annots!.get(index), annotation = annots!.lookup(index, PDFDict)
      const bounds = annotation.lookupMaybe(PDFName.of('Rect'), PDFArray)?.asArray().map(v => v instanceof PDFNumber ? v.asNumber() : NaN)
      if (!bounds || bounds.length !== 4 || !bounds.every(Number.isFinite)) throw new Error('涂黑涉及关联批注或共享外观，无法保证信息完全移除' )
      const [l,b,rr,t] = region.rect, [x1,y1,x2,y2] = bounds
      if (!(Math.min(x1!,x2!) < rr! && Math.max(x1!,x2!) > l! && Math.min(y1!,y2!) < t! && Math.max(y1!,y2!) > b!)) continue
      // Only an exclusive page slot may be removed. Outside IRT/Popup/structure refs
      // would retain the sensitive dictionary after PDFium removes its visible slot.
      if (!(raw instanceof PDFRef) || counts.get(raw.toString()) !== 1 || ['Parent','Popup','StructParent','FS'].some(key => annotation.has(PDFName.of(key)))) throw new Error('涂黑涉及关联批注或共享外观，无法保证信息完全移除' )
      const appearance = annotation.lookupMaybe(PDFName.of('AP'), PDFDict)
      for (const value of [annotation.get(PDFName.of('Contents')), annotation.get(PDFName.of('RC')), annotation.get(PDFName.of('AP')), ...(appearance?.values() ?? [])]) {
        if (value instanceof PDFRef && counts.get(value.toString()) !== 1) throw new Error('涂黑涉及关联批注或共享外观，无法保证信息完全移除' )
      }
    }
  }
}

export async function flattenLayoutAnnotations(content: Uint8Array): Promise<Uint8Array> {
  const source = await PDFDocument.load(content, { updateMetadata: false })
  if (String(source.catalog.lookupMaybe(PDFName.of('AcroForm'),PDFDict)?.lookup(PDFName.of('NeedAppearances'))) === 'true') throw new Error('表单外观尚未确认，暂不能合并页面；请先保存表单外观后重开')
  let visible = false
  for (const page of source.getPages()) {
    const annots = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    for (let index=0; index<(annots?.size() ?? 0); index++) {
      const annotation=annots!.lookup(index, PDFDict), subtype=String(annotation.get(PDFName.of('Subtype')))
      const flags=annotation.lookupMaybe(PDFName.of('F'),PDFNumber)?.asNumber() ?? 0
      if ((flags & (1|2|32)) || ['/Link','/Popup'].includes(subtype)) continue
      const ap=annotation.lookupMaybe(PDFName.of('AP'),PDFDict), normal=ap?.lookup(PDFName.of('N'))
      const selected=normal instanceof PDFDict ? normal.lookup(annotation.get(PDFName.of('AS')) as PDFName) : normal
      if (!(selected instanceof PDFRawStream)) throw new Error('pdf_layout_annotation_appearance_missing')
      visible=true
    }
  }
  const flattened = !visible ? content : await chainPdfium(async () => {
    const module=await loadPdfium()
    const flatten=module as typeof module & { _FPDFPage_Flatten(page:number,flags:number):number }
    if (typeof flatten._FPDFPage_Flatten !== 'function') throw new Error('pdf_layout_flatten_unavailable')
    return withDocument(module,content,async doc => {
      for (let index=0; index<module._FPDF_GetPageCount(doc); index++) {
        const page=module._FPDF_LoadPage(doc,index)
        if (!page) throw new Error('pdf_layout_flatten_failed')
        try { if (flatten._FPDFPage_Flatten(page,0) === 0) throw new Error('pdf_layout_flatten_failed') }
        finally { module._FPDF_ClosePage(page) }
      }
      return saveDoc(module,doc)
    })
  })
  // The pinned embedder assumes a zero-origin MediaBox and ignores CropBox and
  // UserUnit. Normalize the displayed viewport after flattening, keeping the
  // original revision untouched and leaving clipped content clipped in N-up.
  const normalized=await PDFDocument.load(flattened,{updateMetadata:false})
  let changed=false
  for (const page of normalized.getPages()) {
    const crop=page.getCropBox(), media=page.getMediaBox(), unit=page.node.lookupMaybe(PDFName.of('UserUnit'),PDFNumber)?.asNumber() ?? 1
    if (!Number.isFinite(unit) || unit <= 0 || unit > 75000 || !Number.isFinite(crop.width*unit) || !Number.isFinite(crop.height*unit)) throw new Error('页面物理比例超出支持范围')
    if (crop.x===0 && crop.y===0 && crop.x===media.x && crop.y===media.y && crop.width===media.width && crop.height===media.height && unit===1) continue
    if (crop.x || crop.y) page.translateContent(-crop.x,-crop.y)
    if (unit!==1) page.scaleContent(unit,unit)
    page.setMediaBox(0,0,crop.width*unit,crop.height*unit);page.setCropBox(0,0,crop.width*unit,crop.height*unit)
    page.node.delete(PDFName.of('UserUnit'));changed=true
  }
  return changed ? normalized.save({useObjectStreams:false,updateFieldAppearances:false}) : flattened
}
