import type {RenderSlide,PictureRenderNode} from '@genoffice/pptx-render'
import {decodeInkPayload,inkNodesOf,rasterizeStroke,INK_NAME_PREFIX,type InkStroke} from './vendor/genoffice-slides/ink'
export type InkImage={slideIndex:number;bytesBase64:string;extension:'png'|'jpg';geometry:{x:number;y:number;width:number;height:number};name?:string;descr?:string}
export type InkChanges={images?:InkImage[];deletions?:{slideIndex:number;elementId:string}[]}
export function createInkImage(stroke:InkStroke,slideIndex:number):InkImage {
 const raster=rasterizeStroke(stroke)
 if(raster.payload.length>10000)throw Error('这笔墨迹过长，请分成较短笔画；原草稿未改变')
 return {slideIndex,bytesBase64:raster.base64,extension:'png',geometry:{x:raster.xPx,y:raster.yPx,width:raster.wPx,height:raster.hPx},name:INK_NAME_PREFIX+' '+crypto.randomUUID(),descr:raster.payload}
}
export function inkSlide(slide:RenderSlide,slideIndex:number,changes:InkChanges):RenderSlide {
 const removed=new Set(changes.deletions?.filter(d=>d.slideIndex===slideIndex).map(d=>d.elementId))
 const pending=(changes.images??[]).filter(image=>image.slideIndex===slideIndex&&image.name?.startsWith(INK_NAME_PREFIX+' ')&&decodeInkPayload(image.descr??''))
 return {...slide,nodes:[...slide.nodes.filter(n=>!removed.has(n.sourceId)),...pending.map((image,index)=>({id:'ink-pending-'+index,sourceId:'ink-pending:'+image.name,type:'picture' as const,name:image.name,descr:image.descr,dataUrl:'data:image/png;base64,'+image.bytesBase64,box:{x:image.geometry.x,y:image.geometry.y,w:image.geometry.width,h:image.geometry.height,rotationDeg:0,flipH:false,flipV:false}} as PictureRenderNode))]}
}
export function eraseInk<T extends InkChanges>(changes:T,slide:RenderSlide,slideIndex:number,ids?:string[]):T {
 const own=inkNodesOf(inkSlide(slide,slideIndex,changes));const selected=new Set(ids??own.map(e=>e.node.sourceId));const allowed=own.filter(e=>selected.has(e.node.sourceId));const pending=new Set(allowed.filter(e=>e.node.sourceId.startsWith('ink-pending:')).map(e=>e.node.name))
 return {...changes,images:(changes.images??[]).filter(i=>i.slideIndex!==slideIndex||!pending.has(i.name)),deletions:[...(changes.deletions??[]),...allowed.filter(e=>!e.node.sourceId.startsWith('ink-pending:')).map(e=>({slideIndex,elementId:e.node.sourceId}))]}
}
