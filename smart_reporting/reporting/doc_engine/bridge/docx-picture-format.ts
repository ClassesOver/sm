/** Fixed GenOffice f8c17004: Ribbon.tsx rotatePicture/flipPicture/setPicturePx,
 * WRAP_OPTIONS; generate.ts patchImageParagraphXml/applyImageWrap. No bitmap baking. */
import JSZip from 'jszip'
import {parseDocx} from '../packages/docx-engine/src/parse'
import {patchImageParagraphXml,applyImageWrap,type ImagePatch} from '../packages/docx-engine/src/generate'
import type {ImageWrap} from '../packages/docx-engine/src/types'
import {inspectDocxPicture} from './docx-picture'
import {docxInsertionHash} from './docx-field'
import {docxTocSource} from './docx-toc-core'
import {assertZipIdentity} from './docx-comment-source'
export const DOCX_PICTURE_WRAPS = ['square-left','square-right','tight-left','tight-right','through-left','through-right','topBottom','behind','front'] as const
export type DocxPictureFormat = ImagePatch & {wrap?:ImageWrap|null;posH?:'left'|'center'|'right';posV?:'top'|'center'|'bottom'}
export type DocxPictureFormatOperation = DocxPictureFormat & {kind:'formatImage';blockId:string;expectedObjectSha256:string;expectedImageSha256:string}
const fields=['widthPx','heightPx','align','rotDeg','flipH','flipV','wrap','posH','posV']
export function readDocxPictureFormat(value:unknown):DocxPictureFormatOperation {
 const op=value as DocxPictureFormatOperation
 if(!op||typeof op!=='object'||Array.isArray(op)||op.kind!=='formatImage'||Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','expectedImageSha256',...fields].includes(k))||![op.blockId,op.expectedObjectSha256,op.expectedImageSha256].every(v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v))||!fields.some(k=>Object.hasOwn(op,k)))throw new Error('docx_picture_format_operation')
 for(const k of ['widthPx','heightPx'] as const)if(op[k]!==undefined&&(!Number.isInteger(op[k])||op[k]!<1||op[k]!>10000))throw new Error('docx_picture_format_dimensions')
 if((op.widthPx===undefined)!==(op.heightPx===undefined))throw new Error('docx_picture_format_dimensions')
 if(op.rotDeg!==undefined&&(!Number.isInteger(op.rotDeg)||op.rotDeg<0||op.rotDeg>359))throw new Error('docx_picture_format_rotation')
 for(const k of ['flipH','flipV'] as const)if(op[k]!==undefined&&typeof op[k]!=='boolean')throw new Error('docx_picture_format_flip')
 if(op.align!==undefined&&op.align!==null&&!['left','center','right'].includes(op.align))throw new Error('docx_picture_format_align')
 if(op.wrap!==undefined&&op.wrap!==null&&!DOCX_PICTURE_WRAPS.includes(op.wrap))throw new Error('docx_picture_format_wrap')
 if((op.posH===undefined)!==(op.posV===undefined)||op.posH!==undefined&&(!['left','center','right'].includes(op.posH)||!['top','center','bottom'].includes(op.posV!)||op.wrap!==(op.posH==='right'?'square-right':'square-left')))throw new Error('docx_picture_format_position')
 return op
}
export async function inspectDocxPictureFormats(bytes:Uint8Array,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 assertZipIdentity(bytes);parsed=await parseDocx(bytes)
 return formatsOf(bytes,parsed)
}
function formatsOf(bytes:Uint8Array,parsed:Awaited<ReturnType<typeof parseDocx>>){
 const source=docxTocSource(parsed),hash=docxInsertionHash(bytes)
 if(!source.safe)return []
 return parsed.blocks.flatMap(b=>{
  const p=inspectDocxPicture(b,!!parsed.protection?.enforced)
  if(!p.imageEditable||b.docxIndex==null||!source.paragraphs.has(b.docxIndex)||!b.originalXml||!/<pic:spPr\b[^>]*>[\s\S]*?<a:xfrm\b/.test(b.originalXml))return []
  return [{blockId:docxInsertionHash(hash+':block:'+b.docxIndex),expectedObjectSha256:docxInsertionHash(b.originalXml),expectedImageSha256:p.imageSha256!}]
 })
}
export async function patchDocxPictureFormat(bytes:Uint8Array,value:unknown,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 const op=readDocxPictureFormat(value);assertZipIdentity(bytes);parsed=await parseDocx(bytes)
 const target=formatsOf(bytes,parsed).find(t=>t.blockId===op.blockId&&t.expectedObjectSha256===op.expectedObjectSha256&&t.expectedImageSha256===op.expectedImageSha256)
 if(!target)throw new Error('docx_picture_format_anchor')
 const hash=docxInsertionHash(bytes),b=parsed.blocks.find(b=>b.docxIndex!=null&&docxInsertionHash(hash+':block:'+b.docxIndex)===op.blockId)!,source=docxTocSource(parsed),range=source.paragraphs.get(b.docxIndex!)!
 let xml=patchImageParagraphXml(b.originalXml!,op)
 // Only a deliberate wrap change rebuilds anchor positions; other edits preserve producer geometry.
 if(op.wrap!==undefined){
  if(parsed.blocks.some(b=>b.imageZOrderNormalized))throw new Error('docx_picture_format_wrap_normalized_zorder_unsupported')
  xml=applyImageWrap(xml,op.wrap,undefined,op.posH&&op.posV?{h:op.posH,v:op.posV}:undefined,b.imageZOrder)
 }
 const zip=await JSZip.loadAsync(bytes);zip.file('word/document.xml',source.xml.slice(0,range.start)+xml+source.xml.slice(range.end),{createFolders:false})
 return zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}
