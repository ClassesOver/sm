/** 固定源 ZoomDialog 缩略图网格：单选、Ctrl/Command 多选与 aria-pressed。 */
import React,{useState} from 'react'
import {createRoot} from 'react-dom/client'
import type {RenderSlide} from '@genoffice/pptx-render'
import {SlideThumb} from './vendor/genoffice/renderer/SlideThumb'
import './slides-zoom-grid.css'
export async function mountZoomGrid(host:HTMLElement,items:{index:number;caption:string;slide:RenderSlide}[],onChange:(indices:number[])=>void,signal:AbortSignal){
 const urls=new Set<string>(),images=new Map<string,HTMLImageElement>()
 const collect=(value:unknown)=>{if(typeof value==='string'&&value.startsWith('data:image/'))urls.add(value);else if(value&&typeof value==='object')for(const child of Object.values(value))collect(child)};collect(items)
 await Promise.all([...urls].map(url=>new Promise<void>((resolve,reject)=>{const image=new Image();images.set(url,image);const cleanup=()=>{image.onload=null;image.onerror=null;signal.removeEventListener('abort',abort)};const abort=()=>{cleanup();image.removeAttribute('src');reject(new DOMException('已取消','AbortError'))};image.onload=()=>{cleanup();resolve()};image.onerror=()=>{cleanup();reject(Error('缩略图读取失败'))};signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();else image.src=url})))
 if(signal.aborted)throw new DOMException('已取消','AbortError')
 host.classList.add('slides-zoom-grid')
 const root=createRoot(host)
 function Grid(){const [selected,setSelected]=useState<number[]>([]);return <>{items.map(item=><button key={item.index} type="button" aria-pressed={selected.includes(item.index)} onClick={event=>{const next=event.ctrlKey||event.metaKey?(selected.includes(item.index)?selected.filter(index=>index!==item.index):[...selected,item.index]):[item.index];setSelected(next);onChange(next)}}><SlideThumb slide={item.slide} images={images} width={160}/><span>{item.caption}</span></button>)}</>}
 root.render(<Grid/>);signal.addEventListener('abort',()=>root.unmount(),{once:true})
}
