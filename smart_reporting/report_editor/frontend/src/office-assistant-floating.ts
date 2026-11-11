import {createElement,PanelsTopLeft,PanelRight} from 'lucide'
import './office-assistant-floating.css'

/** 浮动只改变位置，不搬动面板或重建任务控制器。 */
export function bindOfficeAssistantFloating(dock:HTMLElement,header:HTMLElement){
 const toggle=document.createElement('button');toggle.type='button';toggle.className='office-assistant-float-toggle'
 header.classList.add('office-assistant-window-header');header.append(toggle)
 const handle=document.createElement('span');handle.className='office-assistant-drag-handle';handle.tabIndex=0;handle.setAttribute('role','button');handle.setAttribute('aria-label','移动 AI 助手（方向键调整）');handle.textContent='⠿';header.prepend(handle)
 let floating=false,x=0,y=0,drag:{id:number;x:number;y:number;left:number;top:number}|undefined
 const place=()=>{
  const rect=dock.getBoundingClientRect()
  x=Math.max(8,Math.min(x,Math.max(8,window.innerWidth-rect.width-8)))
  y=Math.max(8,Math.min(y,Math.max(8,window.innerHeight-rect.height-8)))
  dock.style.left=x+'px';dock.style.top=y+'px'
 }
 const setFloating=(value:boolean)=>{
  const rect=dock.getBoundingClientRect();floating=value;dock.classList.toggle('is-office-assistant-floating',value)
  toggle.setAttribute('aria-pressed',String(value));toggle.setAttribute('aria-label',value?'停靠 AI 助手':'浮动 AI 助手');toggle.title=value?'停靠到右侧':'浮动窗口'
  toggle.replaceChildren(createElement(value?PanelRight:PanelsTopLeft,{width:17,height:17,'aria-hidden':'true'}))
  if(value){x=rect.left;y=rect.top;place()}else{dock.style.removeProperty('left');dock.style.removeProperty('top')}
 }
 toggle.onclick=()=>setFloating(!floating)
 const start=(event:PointerEvent)=>{
  if(!floating||event.button!==0||(event.target as Element).closest('button'))return
  event.preventDefault();const rect=dock.getBoundingClientRect();drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:rect.left,top:rect.top};header.setPointerCapture(event.pointerId)
 }
 const move=(event:PointerEvent)=>{if(!drag||drag.id!==event.pointerId)return;x=drag.left+event.clientX-drag.x;y=drag.top+event.clientY-drag.y;place()}
 const end=(event:PointerEvent)=>{if(drag?.id!==event.pointerId)return;drag=undefined;if(header.hasPointerCapture(event.pointerId))header.releasePointerCapture(event.pointerId)}
 const key=(event:KeyboardEvent)=>{
  if(!floating||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return
  event.preventDefault();x+=event.key==='ArrowLeft'?-20:event.key==='ArrowRight'?20:0;y+=event.key==='ArrowUp'?-20:event.key==='ArrowDown'?20:0;place()
 }
 const viewport=()=>{if(floating)place()}
 header.addEventListener('pointerdown',start);header.addEventListener('pointermove',move);header.addEventListener('pointerup',end);header.addEventListener('pointercancel',end);handle.addEventListener('keydown',key);window.addEventListener('resize',viewport)
 setFloating(false)
 return{dispose(){header.removeEventListener('pointerdown',start);header.removeEventListener('pointermove',move);header.removeEventListener('pointerup',end);header.removeEventListener('pointercancel',end);handle.removeEventListener('keydown',key);window.removeEventListener('resize',viewport);toggle.remove();handle.remove();dock.classList.remove('is-office-assistant-floating')}}
}
