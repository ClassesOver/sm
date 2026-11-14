import React from 'react'
import {createRoot} from 'react-dom/client'
import type {RenderSlide} from '@genoffice/pptx-render'
import {RibbonDrawTab,type PenPanel} from './vendor/genoffice-slides/components/DrawTab'
import {InkOverlay} from './vendor/genoffice-slides/InkOverlay'
import {inkNodesOf,isPenKind,type InkTool} from './vendor/genoffice-slides/ink'
import {loadInkPresets,saveInkPresets,type InkPreset} from './vendor/genoffice-slides/ink-presets'
import {createInkImage,eraseInk,inkSlide,type InkChanges} from './slides-ink-model'
import './slides-ink.css'
type State={slide:RenderSlide|undefined;slideIndex:number;changes:InkChanges;key:string;available:boolean}
/** 源DrawTab/InkOverlay的宿主：每笔只有既有NativeDraft一次提交。 */
export function mountSlidesInk(panel:HTMLElement,options:{canvas:()=>HTMLElement|undefined;state:()=>State;commit:(changes:InkChanges)=>void;status:(message:string)=>void}) {
 panel.classList.add('slides-ink-panel')
 const root=createRoot(panel),layer=document.createElement('div');layer.className='slides-ink-layer';document.body.append(layer);const overlay=createRoot(layer)
 let presets=loadInkPresets().map(p=>({...p})),activeId=presets[0]!.id,tool:InkTool='select',popup:PenPanel|null=null,disposed=false,epoch=0,lastKey='',frame=0
 const position=()=>{const canvas=options.canvas(),rect=canvas?.getBoundingClientRect();if(rect){Object.assign(layer.style,{left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:rect.height+'px'});layer.hidden=rect.width<=0||rect.height<=0}else layer.hidden=true}
 function render(){
  if(disposed)return
  const state=options.state(),key=state.key+'|'+tool,active=presets.find(p=>p.id===activeId)??presets[0]!
  if(key!==lastKey){lastKey=key;epoch++}
  if(!state.available){tool='select';popup=null}
  const projected=state.slide?inkSlide(state.slide,state.slideIndex,state.changes):undefined
  const current=()=>!disposed&&state.available&&options.state().available&&options.state().key===state.key
  const run=(action:()=>void)=>{if(!current())return;try{action()}catch(error){options.status(error instanceof Error?error.message:String(error))}}
  root.render(<RibbonDrawTab hasDoc={state.available} tool={tool} presets={presets} activeId={activeId} onTool={next=>{tool=next;epoch++;render()}} onPresets={next=>{presets=next;saveInkPresets(next);render()}} onActivate={id=>{activeId=id;render()}} inkCount={projected?inkNodesOf(projected).length:0} onClearAll={()=>run(()=>{if(state.slide)options.commit({...state.changes,...eraseInk(state.changes,state.slide,state.slideIndex)})})} panel={popup} setPanel={next=>{popup=next;render()}} closePanels={()=>{}} />)
  overlay.render(projected&&state.available&&(isPenKind(tool)||tool==='eraser')?<InkOverlay key={epoch} slide={projected!} tool={tool as Exclude<InkTool,'select'>} color={active.color} width={active.width} onCommit={stroke=>run(()=>options.commit({...state.changes,images:[...(state.changes.images??[]),createInkImage(stroke,state.slideIndex)]}))} onErase={ids=>run(()=>{if(state.slide)options.commit(eraseInk(options.state().changes,state.slide,state.slideIndex,ids))})}/>:null)
  position();cancelAnimationFrame(frame);frame=requestAnimationFrame(position)
 }
 const cancel=()=>{epoch++;popup=null;tool='select';render()}
 const keydown=(event:KeyboardEvent)=>{if(tool==='select'&&!popup)return;if(event.defaultPrevented||event.isComposing||event.keyCode===229)return;if(event.key==='Escape'){event.preventDefault();cancel()}}
 const outside=(event:PointerEvent)=>{if(popup&&!panel.contains(event.target as Node)){popup=null;render()}}
 const blur=()=>{epoch++;popup=null;render()}
 window.addEventListener('keydown',keydown);window.addEventListener('blur',blur);window.addEventListener('scroll',position,true);window.addEventListener('resize',position);document.addEventListener('pointerdown',outside)
 const observer=new ResizeObserver(position);const canvas=options.canvas();if(canvas)observer.observe(canvas)
 render()
 return {update:render,cancel,dispose(){if(disposed)return;disposed=true;observer.disconnect();cancelAnimationFrame(frame);window.removeEventListener('keydown',keydown);window.removeEventListener('blur',blur);window.removeEventListener('scroll',position,true);window.removeEventListener('resize',position);document.removeEventListener('pointerdown',outside);root.unmount();overlay.unmount();layer.remove()}}
}
