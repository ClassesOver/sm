import React from 'react'
import {createRoot} from 'react-dom/client'
import type Konva from 'konva'
import type {RenderSlide} from '@genoffice/pptx-render'
import {SlideThumb} from './vendor/genoffice/renderer/SlideThumb'

/** 固定源 export-render.tsx 的逐页离屏渲染；沿用 SlideThumb，增加宿主取消与内嵌图像读取。 */
export async function renderSlidesPrintImages(slides:RenderSlide[],signal:AbortSignal):Promise<string[]>{
 const check=()=>{if(signal.aborted)throw new DOMException('打印已取消','AbortError')}
 const wait=<T,>(work:Promise<T>)=>new Promise<T>((resolve,reject)=>{const abort=()=>reject(new DOMException('打印已取消','AbortError'));if(signal.aborted){abort();return}signal.addEventListener('abort',abort,{once:true});work.then(resolve,reject).finally(()=>signal.removeEventListener('abort',abort))})
 check()
 const urls=new Set<string>(),images=new Map<string,HTMLImageElement>()
 const collect=(value:unknown)=>{if(typeof value==='string'&&value.startsWith('data:image/'))urls.add(value);else if(value&&typeof value==='object')for(const child of Object.values(value))collect(child)}
 collect(slides)
 const pendingImages=new Set<()=>void>()
 try{
  await Promise.all([...urls].map(url=>new Promise<void>((resolve,reject)=>{
   const image=new Image();images.set(url,image)
   const cleanup=()=>{image.onload=null;image.onerror=null;signal.removeEventListener('abort',cancel);pendingImages.delete(cancel)}
   const cancel=()=>{cleanup();image.removeAttribute('src');reject(new DOMException('打印已取消','AbortError'))}
   pendingImages.add(cancel);signal.addEventListener('abort',cancel,{once:true})
   image.onload=()=>{cleanup();resolve()}
   image.onerror=()=>{cleanup();reject(Error('幻灯片内嵌图片读取失败'))}
   if(signal.aborted)cancel();else image.src=url
  })))
 }finally{for(const cancel of pendingImages)cancel()}
 if(document.fonts?.ready)await wait(document.fonts.ready)
 check();const container=document.createElement('div');container.style.cssText='position:fixed;left:-100000px;top:0;pointer-events:none';document.body.append(container);const root=createRoot(container),out:string[]=[]
 try{
  for(const [index,slide]of slides.entries()){
   check()
   if(!Number.isFinite(slide.widthPx)||slide.widthPx<=0||!Number.isFinite(slide.heightPx)||slide.heightPx<=0||!Array.isArray(slide.nodes))throw Error('幻灯片打印渲染树无效')
   const stage=await wait(new Promise<Konva.Stage>(resolve=>root.render(<SlideThumb key={index} slide={slide} images={images} width={slide.widthPx} stageRef={stage=>{if(stage)resolve(stage)}}/>)))
   await wait(new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));check();stage.draw()
   const png=stage.toDataURL({mimeType:'image/png',pixelRatio:2});if(!png.startsWith('data:image/png;base64,'))throw Error('幻灯片打印图片未生成');out.push(png)
  }
  return out
 }finally{root.unmount();container.remove()}
}
