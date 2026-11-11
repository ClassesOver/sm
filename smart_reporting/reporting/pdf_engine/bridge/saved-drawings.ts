/** Exact-slot deletion of ordinary saved drawing annotations. No geometry matching. */
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber, PDFRef, PDFRawStream } from 'pdf-lib'
import { markupDictionaryHash, markupSourceId } from './markup-delete'
import { replyReferences } from './note-replies'
export const DRAWING_SUBTYPES = ['Square','Circle','Line','Ink','Polygon','Caret'] as const
export type DrawingSubtype = (typeof DRAWING_SUBTYPES)[number]
export interface SavedDrawing {
  annotationId: string; expectedAnnotationSha256: string; subtype: DrawingSubtype
  annotationIndex: number; rect: [number,number,number,number]; removable: boolean; removalReason: string | null
}
const supported = new Set<string>(DRAWING_SUBTYPES.map(kind=>'/'+kind))
const keys = new Set(['Type','Subtype','Rect','C','IC','F','BS','Border','AP','Contents','T','M','CreationDate','NM','Subj','CA','ca','P','L','LE','InkList','Vertices','Sy','RD'])
export function inspectSavedDrawings(document: PDFDocument, sourceSha256: string, protectedSource: boolean) {
  const counts=replyReferences(document,protectedSource)
  return document.getPages().map((page,pageIndex)=>{
    try {
      const annotations=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
      const drawings: SavedDrawing[]=[]
      for(let index=0;index<(annotations?.size()??0);index++) {
        const raw=annotations!.get(index),annotation=annotations!.lookup(index,PDFDict)
        const subtype=String(annotation.get(PDFName.of('Subtype')))
        if(!supported.has(subtype)) continue
        const bounds=annotation.lookupMaybe(PDFName.of('Rect'),PDFArray)?.asArray().map(value=>value instanceof PDFNumber?value.asNumber():NaN)
        if(!bounds || bounds.length!==4 || !bounds.every(Number.isFinite) || bounds[0]!>=bounds[2]! || bounds[1]!>=bounds[3]!) throw Error('pdf_drawing_bounds_unreadable')
        let reason=counts===null?'此文档的签名或引用结构暂不支持绘图删除':null
        if(!(raw instanceof PDFRef) || counts?.get(raw.toString())!==1) reason ??= '此绘图存在共享或关联引用，暂不能删除'
        if(annotation.keys().some(key=>!keys.has(key.decodeText()))) reason ??= '此绘图含未支持的关系或扩展信息，暂不能删除'
        const parent=annotation.get(PDFName.of('P'))
        if (parent!==undefined && (!(parent instanceof PDFRef) || parent.toString()!==page.ref.toString())) reason ??= '此绘图的来源页面关系无法确认'
        const flags=annotation.lookup(PDFName.of('F'))
        if(flags!==undefined && (!(flags instanceof PDFNumber) || !Number.isInteger(flags.asNumber()) || (flags.asNumber()&~4)!==0)) reason ??= '此绘图有隐藏、锁定或其他未支持的显示标记'
        const ap=annotation.lookupMaybe(PDFName.of('AP'),PDFDict)
        if(ap && (ap.keys().some(key=>key!==PDFName.of('N')) || !(ap.lookup(PDFName.of('N')) instanceof PDFRawStream))) reason ??= '此绘图有多态或无法确认的外观，暂不能删除'
        for(const value of annotation.entries().filter(([key])=>key!==PDFName.of('P')).map(([,value])=>value).concat(ap?.values()??[])) {
          if(value instanceof PDFRef && counts?.get(value.toString())!==1) reason ??= '此绘图存在共享内容或共享外观，暂不能删除'
        }
        drawings.push({annotationId:markupSourceId(sourceSha256,pageIndex,index),expectedAnnotationSha256:markupDictionaryHash(annotation),annotationIndex:index,subtype:subtype.slice(1) as DrawingSubtype,rect:bounds as SavedDrawing['rect'],removable:reason===null,removalReason:reason})
      }
      return {drawings,drawingsReadSafe:true}
    } catch {return {drawings:[] as SavedDrawing[],drawingsReadSafe:false}}
  })
}
