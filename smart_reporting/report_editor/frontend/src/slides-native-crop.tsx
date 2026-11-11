/** 将固定源裁切覆盖层挂到现有画布；坐标始终回传原画布96dpi像素。 */
import React from 'react'
import {createRoot} from 'react-dom/client'
import {CropOverlay,type CropRect} from './vendor/genoffice-slides/CropOverlay'
export type {CropRect} from './vendor/genoffice-slides/CropOverlay'
export type CropGeometry={x:number;y:number;width:number;height:number}
export type SlidesPictureCropOptions={box:CropGeometry;srcRect:CropRect|null;imgSrc:string;slideWidthPx:number;onConfirm:(value:{srcRect:CropRect|null;geometry:CropGeometry})=>void;onCancel:()=>void}
export function openSlidesPictureCrop(host:HTMLElement,options:SlidesPictureCropOptions):{dispose():void}{
 const canvas=host.querySelector('canvas')
 const measure=()=>{
  const hostRect=host.getBoundingClientRect(),canvasRect=host.querySelector('canvas')?.getBoundingClientRect()
  return canvasRect?.width?{left:canvasRect.left-hostRect.left-host.clientLeft+host.scrollLeft,top:canvasRect.top-hostRect.top-host.clientTop+host.scrollTop,width:canvasRect.width,height:canvasRect.height}
   :{left:0,top:0,width:Math.min(host.clientWidth||hostRect.width,options.slideWidthPx),height:host.clientHeight||hostRect.height}
 }
 const bounds=measure(),scale=bounds.width/options.slideWidthPx
 if(!Number.isFinite(scale)||scale<=0)throw Error('画布尚未就绪，请稍后重试裁切')
 const sr=options.srcRect,box=options.box
 const kw=sr?1-sr.l-sr.r:1,kh=sr?1-sr.t-sr.b:1
 if(kw<=0||kh<=0)throw Error('来源裁切范围无效')
 const full={x:box.x-(sr?.l??0)*box.width/kw,y:box.y-(sr?.t??0)*box.height/kh,width:box.width/kw,height:box.height/kh}
 const mount=document.createElement('div');mount.className='slides-native-crop-root'
 Object.assign(mount.style,{position:'absolute',left:`${bounds.left}px`,top:`${bounds.top}px`,width:`${bounds.width}px`,height:`${bounds.height}px`,zIndex:'20'})
 const previousPosition=host.style.position,position=getComputedStyle(host).position
 const changedPosition=!position||position==='static'
 if(changedPosition)host.style.position='relative'
 host.append(mount)
 const root=createRoot(mount)
 let ended=false
 const layoutChanged=()=>{const next=measure();return (['left','top','width','height'] as const).some(key=>Math.abs(next[key]-bounds[key])>.5)}
 const observer=new ResizeObserver(()=>{if(!ended&&layoutChanged())cancel()})
 const dispose=()=>{
  if(ended)return
  ended=true;observer.disconnect();root.unmount();mount.remove()
  if(changedPosition&&host.style.position==='relative')host.style.position=previousPosition
 }
 const cancel=()=>{if(ended)return;dispose();options.onCancel()}
 const confirm=(rect:CropRect|null)=>{
  if(ended)return
  if(layoutChanged()){cancel();return}
  const geometry=rect?{x:full.x+rect.l*full.width,y:full.y+rect.t*full.height,width:full.width*(1-rect.l-rect.r),height:full.height*(1-rect.t-rect.b)}:{...full}
  try{options.onConfirm({srcRect:rect,geometry});dispose()}
  catch(error){
   let alert=mount.querySelector<HTMLElement>('[role=alert]')
   if(!alert){alert=document.createElement('p');alert.setAttribute('role','alert');Object.assign(alert.style,{position:'absolute',left:'8px',top:'8px',background:'white',color:'#a12622',padding:'8px',zIndex:'1',pointerEvents:'none'});mount.append(alert)}
   alert.textContent=error instanceof Error?error.message:'裁切未应用，请取消后重试'
  }
 }
 root.render(<CropOverlay box={{x:box.x*scale,y:box.y*scale,w:box.width*scale,h:box.height*scale}} fullBox={{x:full.x*scale,y:full.y*scale,w:full.width*scale,h:full.height*scale}} imgSrc={options.imgSrc} onConfirm={confirm} onCancel={cancel}/> )
 observer.observe(host)
 if(canvas)observer.observe(canvas)
 return {dispose}
}
