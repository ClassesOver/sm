import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {validatePdfExistingImage,type PdfExistingImage} from './pdf-existing-image'
import type {PdfImageBake} from './pdf-existing-image'
import {bakePdfImagePixels} from './pdf-image-pixels'

type Rect=[number,number,number,number]
export interface PdfImageThumbnailClip {x:number;y:number;width:number;height:number}
export interface PdfImageThumbnailViewport {width:number;height:number;convertToViewportPoint(x:number,y:number):number[]}
export interface PdfImageThumbnailBox {left:number;top:number;width:number;height:number}
export interface PdfExistingImageThumbnailPlan {sourceSha256:string;pageId:string;imageId:string;expectedImageSha256:string;oldRect:Rect;rect:Rect;oldBox:PdfImageThumbnailBox;box:PdfImageThumbnailBox;clip:PdfImageThumbnailClip;pxWidth:number;pxHeight:number;layer:'aboveText'|'belowText';image?:string;bake?:Record<string,unknown>}
export interface PdfImageThumbnailPixels {sourceSha256:string;pageId:string;imageId:string;expectedImageSha256:string;width:number;height:number;image:string;sha256:string}
export interface PdfImageThumbnailBackground extends PdfImageThumbnailPixels {clip:PdfImageThumbnailClip}
export interface PdfImageThumbnailReadyEntry {ready(callback:()=>void):()=>void}

function viewportBox(rect:Rect,viewport:PdfImageThumbnailViewport):PdfImageThumbnailBox{
 const [x1,y1,x2,y2]=rect,points=[[x1,y1],[x1,y2],[x2,y1],[x2,y2]].map(([x,y])=>viewport.convertToViewportPoint(x!,y!)),xs=points.map(point=>point[0]!),ys=points.map(point=>point[1]!),left=Math.min(...xs),top=Math.min(...ys)
 return {left,top,width:Math.max(...xs)-left,height:Math.max(...ys)-top}
}

export function pdfExistingImageThumbnailPlan({sourceSha256,page,operation,images,viewport}:{sourceSha256:string;page:PdfPageIdentity;operation:NativeOperation;images:PdfExistingImage[];viewport:PdfImageThumbnailViewport}):PdfExistingImageThumbnailPlan|null{
 if(operation.kind!=='transformExistingImage'||operation.sourceSha256!==sourceSha256||operation.pageId!==page.pageId||page.pageId!==`sha256:${sourceSha256}:page:${page.index}`||![0,90,180,270].includes(((page.rotation%360)+360)%360))return null
 const matches=images.filter(image=>image.pageId===page.pageId&&image.pageIndex===page.index&&image.imageId===operation.imageId&&image.expectedImageSha256===operation.expectedImageSha256)
 if(matches.length!==1||!matches[0]!.editable)return null
 try{validatePdfExistingImage([page],[operation],images)}catch{return null}
 const target=matches[0]!,oldRect=target.rect,rect=operation.rect as Rect,bake=operation.bake&&typeof operation.bake==='object'?operation.bake as Record<string,unknown>:undefined
 const oldBox=viewportBox(oldRect,viewport),clipLeft=Math.max(0,oldBox.left-2),clipTop=Math.max(0,oldBox.top-2),clipRight=Math.min(viewport.width,oldBox.left+oldBox.width+2),clipBottom=Math.min(viewport.height,oldBox.top+oldBox.height+2),clip={x:clipLeft,y:clipTop,width:clipRight-clipLeft,height:clipBottom-clipTop}
 if(![viewport.width,viewport.height,...Object.values(clip)].every(Number.isFinite)||clip.width<=0||clip.height<=0)return null
 const scale=Math.min(1,720/Math.max(clip.width,clip.height)),pxWidth=Math.max(1,Math.round(clip.width*scale)),pxHeight=Math.max(1,Math.round(clip.height*pxWidth/clip.width))
 if(pxWidth>2400||pxHeight>2400||pxWidth*pxHeight>4_000_000)return null
 return {sourceSha256,pageId:page.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,oldRect,rect,oldBox,box:viewportBox(rect,viewport),clip,pxWidth,pxHeight,layer:target.aboveText?'aboveText':'belowText',image:typeof operation.image==='string'?operation.image:undefined,bake}
}

export async function pdfExistingImageThumbnailPixels(plan:PdfExistingImageThumbnailPlan,pixels:PdfImageThumbnailPixels,sha256Bytes:(bytes:Uint8Array)=>Promise<string>):Promise<string|null>{
 if(pixels.sourceSha256!==plan.sourceSha256||pixels.pageId!==plan.pageId||pixels.imageId!==plan.imageId||pixels.expectedImageSha256!==plan.expectedImageSha256||!Number.isInteger(pixels.width)||!Number.isInteger(pixels.height)||pixels.width<1||pixels.height<1||!/^iVBORw0KGgo[A-Za-z0-9+/]+=*$/.test(pixels.image)||!/^[a-f0-9]{64}$/.test(pixels.sha256))return null
 let actual:string
 try{const binary=atob(pixels.image),bytes=Uint8Array.from(binary,char=>char.charCodeAt(0));actual=await sha256Bytes(bytes)}catch{return null}
 if(actual!==pixels.sha256)return null
 return pixels.image
}

export async function pdfExistingImageThumbnailBackground(plan:PdfExistingImageThumbnailPlan,background:PdfImageThumbnailBackground,sha256Bytes:(bytes:Uint8Array)=>Promise<string>):Promise<string|null>{
 const clipKeys=background.clip&&typeof background.clip==='object'?Object.keys(background.clip).sort():[]
 if(background.sourceSha256!==plan.sourceSha256||background.pageId!==plan.pageId||background.imageId!==plan.imageId||background.expectedImageSha256!==plan.expectedImageSha256||clipKeys.join(',')!=='height,width,x,y'||Object.values(background.clip).some(value=>typeof value!=='number'||!Number.isFinite(value))||Object.keys(plan.clip).some(key=>Math.abs(background.clip[key as keyof PdfImageThumbnailClip]-plan.clip[key as keyof PdfImageThumbnailClip])>1e-6)||!Number.isInteger(background.width)||!Number.isInteger(background.height)||background.width!==plan.pxWidth||background.height!==plan.pxHeight||!/^iVBORw0KGgo[A-Za-z0-9+/]+=*$/.test(background.image)||!/^[a-f0-9]{64}$/.test(background.sha256))return null
 try{
  const bytes=Uint8Array.from(atob(background.image),char=>char.charCodeAt(0))
  if(await sha256Bytes(bytes)!==background.sha256)return null
 }catch{return null}
 return background.image
}

export function mountPdfExistingImageThumbnail({host,plan,viewport,entry,current,loadBackground,loadPixels,sha256Bytes,decode}:{host:HTMLElement;plan:PdfExistingImageThumbnailPlan;viewport:PdfImageThumbnailViewport;entry:PdfImageThumbnailReadyEntry;current:()=>boolean;loadBackground:(signal:AbortSignal,target:{sourceSha256:string;pageId:string;imageId:string;expectedImageSha256:string;clip:PdfImageThumbnailClip;pxWidth:number})=>Promise<PdfImageThumbnailBackground>;loadPixels:(signal:AbortSignal)=>Promise<PdfImageThumbnailPixels>;sha256Bytes:(bytes:Uint8Array)=>Promise<string>;decode:(png:string)=>Promise<HTMLImageElement>}):()=>void{
 const owner=host.ownerDocument,backgroundLayer=owner.createElement('div'),layer=owner.createElement('div'),controller=new AbortController()
 backgroundLayer.className='pdf-existing-image-thumbnail-background'
 Object.assign(backgroundLayer.style,{position:'absolute',left:'0',top:'0',width:'100%',height:'100%',zIndex:'3',mixBlendMode:'normal',pointerEvents:'none'})
 layer.className=`pdf-existing-image-thumbnail-layer pdf-existing-image-thumbnail-${plan.layer}`;layer.dataset.pdfExistingImageThumb=plan.imageId;layer.style.width='100%';layer.style.height='100%'
 const style=(box:PdfImageThumbnailBox)=>({position:'absolute',left:`${box.left/viewport.width*100}%`,top:`${box.top/viewport.height*100}%`,width:`${box.width/viewport.width*100}%`,height:`${box.height/viewport.height*100}%`})
 let cancelled=false,unregister=()=>{}
 const valid=()=>!cancelled&&!controller.signal.aborted&&host.isConnected&&current()
 const cleanup=()=>{if(cancelled)return;cancelled=true;unregister();controller.abort();backgroundLayer.remove();layer.remove()}
 unregister=entry.ready(()=>{
  unregister()
  if(!valid())return
  void (async()=>{
   try{
    const backgroundTarget={sourceSha256:plan.sourceSha256,pageId:plan.pageId,imageId:plan.imageId,expectedImageSha256:plan.expectedImageSha256,clip:plan.clip,pxWidth:plan.pxWidth}
    const [rawBackground,pixels]=await Promise.all([loadBackground(controller.signal,backgroundTarget),plan.image?Promise.resolve(null):loadPixels(controller.signal)])
    if(!valid())return
    const backgroundPng=await pdfExistingImageThumbnailBackground(plan,rawBackground,sha256Bytes)
    if(!backgroundPng||!valid())return
    const decodedBackground=await decode(backgroundPng)
    if(!valid()||decodedBackground.naturalWidth!==plan.pxWidth||decodedBackground.naturalHeight!==plan.pxHeight)return
    let foregroundPng:string
    if(plan.image)foregroundPng=plan.image
    else{
     const png=await pdfExistingImageThumbnailPixels(plan,pixels!,sha256Bytes)
     if(!png||!valid())return
     const decoded=await decode(png)
     if(!valid()||decoded.naturalWidth!==pixels!.width||decoded.naturalHeight!==pixels!.height)return
     foregroundPng=plan.bake?bakePdfImagePixels(decoded,plan.bake as unknown as PdfImageBake):png
    }
    const decodedForeground=await decode(foregroundPng)
    if(!valid()||decodedForeground.naturalWidth<1||decodedForeground.naturalHeight<1)return
    decodedBackground.className='pdf-existing-image-thumbnail-background-image';decodedBackground.alt='';decodedBackground.draggable=false
    Object.assign(decodedBackground.style,{...style({left:plan.clip.x,top:plan.clip.y,width:plan.clip.width,height:plan.clip.height}),position:'absolute',objectFit:'fill',pointerEvents:'none'})
    decodedForeground.className='pdf-existing-image-thumbnail-image';decodedForeground.alt='';decodedForeground.draggable=false;Object.assign(decodedForeground.style,style(plan.box))
    backgroundLayer.append(decodedBackground);layer.append(decodedForeground)
    host.append(backgroundLayer,layer)
   }catch{controller.abort()}
  })()
 })
 return cleanup
}
