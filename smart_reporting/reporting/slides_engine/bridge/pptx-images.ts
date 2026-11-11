/** 图片来源身份与输入边界；OOXML 修改交给固定源引擎。 */
import { createHash } from 'node:crypto'
import { replacePictureBytes, type OpenedPptx } from '@genoffice/pptx-engine'
import { imageSizeFromBytes } from '../packages/pptx-render/src/image-dpi.ts'

export type PictureAsset = { bytesBase64: string; extension: 'png' | 'jpg' }
export type PictureInsertion = PictureAsset & { slideIndex: number; geometry: { x: number; y: number; width: number; height: number }; descr?: string }
export type PictureReplacement = PictureAsset & { slideIndex: number; elementId: string; expectedSha256: string; expectedSize: number }
export type PictureImageIdentity = { slideIndex: number; elementId: string; sha256: string | null; size: number | null; replaceable: boolean; readOnlyReason: string | null }
const MAX_IMAGE_BYTES = 6 * 1024 * 1024
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex')

export function inspectPictureImages(opened: OpenedPptx): PictureImageIdentity[] {
 return opened.deck.slides.flatMap((slide,slideIndex)=>slide.elements.flatMap(element=>{
  if(element.type!=='picture')return []
  const bytes=element.mediaRef ? opened.archive.readBytes(element.mediaRef) : undefined
  const replaceable=!!bytes?.length && /<a:blip\b[^>]*\br:(?:embed|link)="[^"]+"/.test(element.anchor.originalXml)
  return [{slideIndex,elementId:element.id,sha256:bytes?.length?digest(bytes):null,size:bytes?.length??null,replaceable,readOnlyReason:replaceable?null:'图片来源媒体或嵌入身份无法核验'}]
 }))
}
function assetBytes(item: PictureAsset): Buffer {
 if(!item || typeof item.bytesBase64!=='string' || item.bytesBase64.length>Math.ceil(MAX_IMAGE_BYTES/3)*4)throw Error('picture_asset_invalid')
 const bytes=Buffer.from(item.bytesBase64,'base64')
 if(!bytes.length||bytes.length>MAX_IMAGE_BYTES||bytes.toString('base64')!==item.bytesBase64)throw Error('picture_asset_invalid')
 const signature=item.extension==='png'
  ? bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) && bytes.subarray(-12).equals(Buffer.from([0,0,0,0,73,69,78,68,174,66,96,130]))
  : item.extension==='jpg' && bytes[0]===255 && bytes[1]===216 && bytes[2]===255 && bytes.at(-2)===255 && bytes.at(-1)===217
 if(!signature)throw Error('picture_asset_invalid')
 try {
  const size=imageSizeFromBytes(bytes)
  if(!size||!size.w||!size.h||size.w*size.h>100_000_000)throw Error('size')
 }catch{throw Error('picture_asset_invalid')}
 return bytes
}
function validSlide(opened:OpenedPptx,index:number){return Number.isInteger(index)&&index>=0&&index<opened.deck.slides.length}
function validBatch(items:unknown): asserts items is unknown[] {if(!Array.isArray(items)||items.length>50)throw Error('picture_request_invalid')}
export function validatePictureInsertions(opened:OpenedPptx,items:PictureInsertion[]):void {
 validBatch(items)
 let total=0
 for(const item of items){
  if(!item||!validSlide(opened,item.slideIndex))throw Error('picture_target_invalid')
  const g=item.geometry
  if(!g||![g.x,g.y,g.width,g.height].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=100000)||g.width<=0||g.height<=0)throw Error('picture_geometry_invalid')
  if(item.descr!==undefined&&(typeof item.descr!=='string'||item.descr.length>10000))throw Error('picture_description_invalid')
  total+=assetBytes(item).length
  if(total>8*1024*1024)throw Error('picture_budget_exceeded')
 }
}
export function validatePictureReplacements(opened:OpenedPptx,items:PictureReplacement[]):void {
 validBatch(items)
 const identities=inspectPictureImages(opened),seen=new Set<string>();let total=0
 for(const item of items){
  if(!item||!validSlide(opened,item.slideIndex)||typeof item.elementId!=='string')throw Error('picture_target_invalid')
  const key=item.slideIndex+':'+item.elementId
  if(seen.has(key))throw Error('picture_target_duplicate')
  seen.add(key)
  const target=identities.find(p=>p.slideIndex===item.slideIndex&&p.elementId===item.elementId)
  if(!target?.replaceable)throw Error('picture_target_invalid')
  if(target.sha256!==item.expectedSha256||target.size!==item.expectedSize)throw Error('picture_identity_changed')
  total+=assetBytes(item).length
  if(total>8*1024*1024)throw Error('picture_budget_exceeded')
 }
}
export function applyPictureReplacements(opened:OpenedPptx,items:PictureReplacement[]):void {
 validatePictureReplacements(opened,items)
 for(const item of items){
  if(!replacePictureBytes(opened,opened.deck.slides[item.slideIndex]!,item.elementId,assetBytes(item),item.extension))throw Error('picture_replace_failed')
 }
}
