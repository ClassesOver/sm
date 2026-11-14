/** 固定源scene/views/TurnHandle的web宿主；写入仅经既有NativeDraft。 */
import React from 'react'
import {createRoot} from 'react-dom/client'
import type {PictureRenderNode} from '@genoffice/pptx-render'
import {NO_ROTATION,type Model3dRotation} from '@genoffice/pptx-engine/model3d'
import {validateLocalGlb} from '@genoffice/pptx-engine/glb-resources'
import {Model3dTurnHandle} from './vendor/genoffice-slides/model3d/Model3dTurnHandle'
import {MODEL3D_VIEWS} from './vendor/genoffice-slides/model3d/views'
import {loadModel,renderingSize,type ModelView} from './vendor/genoffice-slides/model3d/scene'
import {Icon3d} from './vendor/genoffice-slides/components/icons'
import {bytes64,from64,turnModelDraft,type ModelChanges,type ModelSource} from './slides-model3d'
import './slides-model3d.css'
type State={key:string;available:boolean;slideIndex:number;width:number;height:number;source?:ModelSource;node?:PictureRenderNode;insertionKey?:string;changes:ModelChanges}
const labels=['正面','背面','左侧','右侧','顶部','底部','左前上方']
export function mountModel3d(panel:HTMLElement,options:{state:()=>State;canvas:()=>HTMLElement|undefined;commit:(changes:ModelChanges)=>void;status:(message:string)=>void}){
 panel.classList.add('slides-model3d-panel')
 const ribbon=createRoot(panel),layer=document.createElement('div');layer.className='slides-model3d-layer';document.body.append(layer);const overlay=createRoot(layer)
 let disposed=false,pending=false,picker:HTMLInputElement|undefined
 const current=(state:State)=>!disposed&&!pending&&options.state().available&&state.key===options.state().key
 const position=()=>{const rect=options.canvas()?.getBoundingClientRect(),state=options.state();if(!rect){layer.hidden=true;return}layer.hidden=!state.available;Object.assign(layer.style,{left:rect.left+'px',top:rect.top+'px',width:state.width+'px',height:state.height+'px',transform:`scale(${rect.width/state.width},${rect.height/state.height})`})}
 async function turn(state:State,rot:Model3dRotation,loaded?:ModelView){
  if(!current(state)||!state.source?.bytesBase64||!state.node)return
  pending=true;update();let view=loaded
  try{
   view??=await loadModel(from64(state.source.bytesBase64))
   const size=renderingSize(state.node.box.w,state.node.box.h),png=await view.png(size.width,size.height,rot)
   if(disposed||state.key!==options.state().key||!options.state().available)return
   options.commit(turnModelDraft(state.changes,state.slideIndex,state.source,state.insertionKey,rot,bytes64(png)))
  }catch(error){if(!disposed)options.status(error instanceof Error?error.message:String(error))}
  finally{if(!loaded)view?.dispose();pending=false;update()}
 }
 function update(){
  if(disposed)return
  const state=options.state(),canTurn=state.available&&!pending&&!!state.source?.bytesBase64&&!!state.node
  ribbon.render(<section className="ribbon-group"><div className="ribbon-group-items"><button className="rb-big" data-model3d-reset disabled={!canTurn} onClick={()=>void turn(state,NO_ROTATION)}><span className="rb-big-icon"><Icon3d size={28}/></span><span>重置模型</span></button>{[0,3,6].map(start=><div className="rb-col" key={start}>{MODEL3D_VIEWS.slice(start,start+3).map(({label,rot},i)=><button className="rb-small" data-model3d-view={start+i} key={label} disabled={!canTurn} onClick={()=>void turn(state,rot)}><Icon3d size={18}/><span>{labels[start+i]}</span></button>)}</div>)}</div><div className="ribbon-group-label">3D模型视图</div></section>)
  layer.dataset.pending=String(pending)
  overlay.render(state.available&&state.node&&state.source?<Model3dTurnHandle key={state.key} node={{...state.node,model3d:state.source.rot}} slideIndex={state.slideIndex} readData={async()=>{if(!current(state)||!state.source?.bytesBase64)throw Error('模型来源已变化');return from64(state.source.bytesBase64)}} onTurn={(rot,view)=>turn(state,rot,view)} onError={error=>options.status(error instanceof Error?error.message:String(error))}/>:null)
  position()
 }
 async function insert(){
  const state=options.state();if(!current(state))return
  picker?.remove();picker=document.createElement('input');picker.type='file';picker.accept='.glb,model/gltf-binary';picker.hidden=true;document.body.append(picker)
  picker.addEventListener('change',async()=>{
   const file=picker?.files?.[0];picker?.remove();picker=undefined;if(!file||!current(state))return
   pending=true;update();let view:ModelView|undefined
   try{
    if(!/\.glb$/i.test(file.name)||file.size>6*1024*1024)throw Error('请选择不超过6MiB的自包含GLB文件')
    const data=new Uint8Array(await file.arrayBuffer());validateLocalGlb(data);view=await loadModel(data)
    const aspect=Math.max(1/3,Math.min(3,view.frontAspect)),height=state.height*.5,size=renderingSize(height*aspect,height)
    const poster=await view.png(size.width,size.height,NO_ROTATION)
    if(disposed||state.key!==options.state().key||!options.state().available)return
    options.commit({...state.changes,modelInsertions:[...(state.changes.modelInsertions??[]),{slideIndex:state.slideIndex,key:crypto.randomUUID(),name:file.name,bytesBase64:bytes64(data),posterBase64:bytes64(poster),aspect,rot:{...NO_ROTATION}}]})
   }catch(error){if(!disposed)options.status(error instanceof Error?error.message:String(error))}
   finally{view?.dispose();pending=false;update()}
  },{once:true});picker.click()
 }
 window.addEventListener('scroll',position,true);window.addEventListener('resize',position)
 const observer=new ResizeObserver(position);const canvas=options.canvas();if(canvas)observer.observe(canvas)
 update()
 return {update,insert,dispose(){disposed=true;picker?.remove();observer.disconnect();window.removeEventListener('scroll',position,true);window.removeEventListener('resize',position);ribbon.unmount();overlay.unmount();layer.remove()}}
}
