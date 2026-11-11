/** 普通嵌入图片的无损裁切；宿主整批先验并只签发最终保存产物，NativeDraft一次撤销框与裁切。 */
import {createHash} from 'node:crypto'
import {editPictureSrcRect,updateConnectorsForMoved,type OpenedPptx} from '@genoffice/pptx-engine'
import {imageSizeFromBytes} from '../packages/pptx-render/src/image-dpi.ts'
import {resolveTarget} from '../packages/pptx-engine/src/zip.ts'
export type CropRect={l:number;t:number;r:number;b:number}
export type PictureCrop={slideIndex:number;elementId:string;expectedSha256:string;expectedSize:number;srcRect:CropRect|null;geometry:{x:number;y:number;width:number;height:number}}
type Target={slideIndex:number;elementId:string}
type Conflicts={deletedSlides?:readonly number[];deletions?:readonly Target[];pictureReplacements?:readonly Target[]}
const reason='仅支持无旋转、无翻转的普通嵌入 PNG/JPEG 图片裁切'
function cropRect(value:unknown):value is CropRect|null{
 if(value===null)return true
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join()!=='b,l,r,t')return false
 const r=value as CropRect
 return [r.l,r.t,r.r,r.b].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<1)&&r.l+r.r<1&&r.t+r.b<1
}
export function inspectPictureCrop(opened:OpenedPptx,slideIndex:number,elementId:string):{pictureCropEditable:boolean;pictureCropReason:string|null;srcRect:CropRect|null}{
 const unavailable={pictureCropEditable:false,pictureCropReason:reason,srcRect:null}
 const slide=opened.deck.slides[slideIndex],element=slide?.elements.find(e=>e.id===elementId)
 if(!slide||element?.type!=='picture')return unavailable
 const t=element.transform,xml=element.anchor.originalXml
 if(t.rot!==0||t.flipH||t.flipV||element.placeholder||element.media||element.model3d||element.tile||element.scene3d||element.customGeometry||(element.presetGeometry&&element.presetGeometry!=='rect')||element.duotone||element.clrChange||element.lum||element.biLevel!==undefined||/<(?:\w+:)?(?:AlternateContent|oleObj)\b|\br:link=/.test(xml)||!cropRect(element.srcRect??null))return unavailable
 const embeds=[...xml.matchAll(/<a:blip\b[^>]*\br:embed="([^"]+)"/g)]
 if(embeds.length!==1)return unavailable
 const rel=opened.archive.readRels(slide.path).get(embeds[0]![1]!)
 if(!rel||!rel.type.endsWith('/image')||rel.targetMode==='External'||resolveTarget(slide.path,rel.target)!==element.mediaRef)return unavailable
 const bytes=opened.archive.readBytes(element.mediaRef)
 if(!bytes||!imageSizeFromBytes(bytes)||!((bytes[0]===137&&bytes[1]===80)||(bytes[0]===255&&bytes[1]===216)))return unavailable
 const o=t.offset
 if(![o.x,o.y,o.cx,o.cy].every(Number.isFinite)||o.cx<=0||o.cy<=0)return unavailable
 return {pictureCropEditable:true,pictureCropReason:null,srcRect:element.srcRect?{...element.srcRect}:null}
}
export function validatePictureCrops(opened:OpenedPptx,input:unknown,conflicts:Conflicts={}):PictureCrop[]{
 if(input===undefined)return []
 if(!Array.isArray(input)||input.length>50)throw Error('picture_crop_request_invalid')
 const seen=new Set<string>()
 for(const item of input){
  if(!item||typeof item!=='object'||Object.keys(item).sort().join()!=='elementId,expectedSha256,expectedSize,geometry,slideIndex,srcRect'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=opened.deck.slides.length||typeof item.elementId!=='string'||!cropRect(item.srcRect))throw Error('picture_crop_invalid')
  const key=`${item.slideIndex}:${item.elementId}`
  if(seen.has(key)||conflicts.deletedSlides?.includes(item.slideIndex)||[...(conflicts.deletions??[]),...(conflicts.pictureReplacements??[])].some(target=>target.slideIndex===item.slideIndex&&target.elementId===item.elementId))throw Error('picture_crop_target_conflict')
  seen.add(key)
  const g=item.geometry
  if(!g||typeof g!=='object'||Object.keys(g).sort().join()!=='height,width,x,y'||![g.x,g.y,g.width,g.height].every(n=>typeof n==='number'&&Number.isFinite(n)&&Math.abs(n)<=100000)||g.width<=0||g.height<=0)throw Error('picture_crop_geometry_invalid')
  if(!inspectPictureCrop(opened,item.slideIndex,item.elementId).pictureCropEditable)throw Error('picture_crop_source_unsupported')
  const element=opened.deck.slides[item.slideIndex]!.elements.find(e=>e.id===item.elementId)!
  const bytes=opened.archive.readBytes((element as {mediaRef:string}).mediaRef)!
  if(typeof item.expectedSha256!=='string'||!/^[a-f0-9]{64}$/.test(item.expectedSha256)||!Number.isSafeInteger(item.expectedSize)||item.expectedSize!==bytes.length||createHash('sha256').update(bytes).digest('hex')!==item.expectedSha256)throw Error('picture_crop_identity_changed')
 }
 return input as PictureCrop[]
}
export function applyPictureCrops(opened:OpenedPptx,items:PictureCrop[]):void{
 validatePictureCrops(opened,items)
 if(!items.length)return
 const moved=new Map<number,string[]>()
 for(const item of items){
  const slide=opened.deck.slides[item.slideIndex]!
  const element=slide.elements.find(e=>e.id===item.elementId)!
  if(!editPictureSrcRect(slide,item.elementId,item.srcRect))throw Error('picture_crop_apply_failed')
  element.transform={...element.transform,offset:{x:Math.round(item.geometry.x*9525),y:Math.round(item.geometry.y*9525),cx:Math.round(item.geometry.width*9525),cy:Math.round(item.geometry.height*9525)}}
  element.dirtyTransform=true
  moved.set(item.slideIndex,[...(moved.get(item.slideIndex)??[]),item.elementId])
 }
 for(const [slideIndex,ids] of moved)updateConnectorsForMoved(opened.deck.slides[slideIndex]!,ids)
}
