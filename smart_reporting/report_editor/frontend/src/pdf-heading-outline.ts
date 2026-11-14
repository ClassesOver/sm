import type {PDFDocumentProxy} from 'pdfjs-dist'
import {buildHeadingOutline} from './vendor/genoffice-pdf/renderer/heading-outline'
import {resolvePdfOutline,type PdfOutlineItem,type ResolvedPdfOutlineItem} from './pdf-view-ribbon'

/** 固定源 App 读取生命周期：嵌入目录优先，标题推导只读且丢弃过期文档结果。 */
export async function readPdfNavigationOutline(document:PDFDocumentProxy,cancelled:()=>boolean=()=>false):Promise<{items:ResolvedPdfOutlineItem[];generated:boolean}|null>{
 const embedded=await document.getOutline().catch(()=>null)
 if(cancelled())return null
 const generated=embedded?.length?null:await buildHeadingOutline(document,cancelled).catch(()=>null)
 if(cancelled())return null
 const nodes=embedded?.length?embedded:generated
 const items=await resolvePdfOutline((nodes??[]) as PdfOutlineItem[],document)
 return cancelled()?null:{items,generated:!embedded?.length&&generated!==null}
}
