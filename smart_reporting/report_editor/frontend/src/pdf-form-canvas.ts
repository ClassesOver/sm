/** Fixed GenOffice f8c17004 single-widget selection and screen-direction arrow nudge. */
import type {NativeOperation} from './native-draft'
import {stagePdfFormWidgetProperties,type PdfFormCreateModel,type PdfFormWidgetTarget} from './pdf-form-create'
import {pdfRectToCss,viewToPdf,geomDispSize} from '../../../reporting/pdf_engine/bridge/form-design-layout'
export type PdfFormCanvasSelection=PdfFormWidgetTarget&{sourceSha256:string;pageId:string}
export interface PdfFormCanvasController {sync():boolean;clear():void;dispose():void}
interface Options {
 editor:HTMLElement;host:HTMLElement;pageId:string
 viewport:{width:number;height:number;convertToViewportPoint(x:number,y:number):number[]}
 model():PdfFormCreateModel;operations():NativeOperation[];current():boolean
 selected():PdfFormCanvasSelection|undefined;select(selection:PdfFormCanvasSelection|undefined):void
 commit(operations:NativeOperation[]):void;error(error:unknown):void
}
const NS='http://www.w3.org/2000/svg',identityKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256']as const
const directions:Record<string,readonly[number,number]>={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}
const target=(selection:PdfFormCanvasSelection):PdfFormWidgetTarget=>({fieldName:selection.fieldName,widgetId:selection.widgetId,widgetIdentity:selection.widgetIdentity,expectedWidgetSha256:selection.expectedWidgetSha256})
const same=(a:PdfFormCanvasSelection|undefined,b:PdfFormCanvasSelection)=>!!a&&a.sourceSha256===b.sourceSha256&&a.pageId===b.pageId&&identityKeys.every(k=>a[k]===b[k])
const equalRect=(a:readonly number[],b:readonly number[])=>a.length===4&&b.length===4&&a.every((v,i)=>Math.abs(v-b[i])<1e-8)
function currentWidget(model:PdfFormCreateModel,operations:NativeOperation[],selection:PdfFormCanvasSelection){
 if(selection.sourceSha256!==model.sourceSha256)throw Error('字段来源身份已变化')
 const widgets=model.formDesignWidgets??[],matches=widgets.filter(w=>identityKeys.every(k=>w[k]===selection[k])),widget=matches[0]
 if(matches.length!==1||!widget?.designEditable||widgets.filter(w=>w.fieldName===widget.fieldName).length!==1)throw Error('画布微调仅支持身份完整的独立单控件字段')
 const page=model.pages.find((p,i)=>(p.index??i)===widget.pageIndex)
 if(!page||page.pageId!==selection.pageId)throw Error('字段页面身份已变化')
 stagePdfFormWidgetProperties(model,[],target(selection),{rect:widget.rect})
 let rect=widget.rect
 if(operations.length){const op=operations[0]
  if(operations.length!==1||op.kind!=='editFormWidget'||op.sourceSha256!==selection.sourceSha256||!identityKeys.every(k=>op[k]===selection[k])||Object.keys(op).some(k=>!['kind','sourceSha256',...identityKeys,'rect'].includes(k))||op.rect===undefined)throw Error('画布微调须单独保存，不能合并其他字段或属性修改')
  stagePdfFormWidgetProperties(model,[],target(selection),{rect:op.rect as [number,number,number,number]});rect=op.rect as [number,number,number,number]
 }
 return {widget,page,rect}
}
/** Replaces this source-bound rect operation rather than appending one operation per key. */
export function stagePdfFormWidgetNudge(model:PdfFormCreateModel,operations:NativeOperation[],selection:PdfFormCanvasSelection,key:string,shift=false):NativeOperation[]{
 const delta=directions[key];if(!delta)throw Error('微调仅支持方向键')
 const {widget,page,rect}=currentWidget(model,operations,selection),b=page.cropBox,geom={pw:b.width,ph:b.height,x0:b.x,y0:b.y,rot:page.rotation??0},box=pdfRectToCss(geom,rect,1),size=geomDispSize(geom),step=shift?10:1
 const left=Math.min(Math.max(box.left+delta[0]*step,0),size.width-box.width),top=Math.min(Math.max(box.top+delta[1]*step,0),size.height-box.height),a=viewToPdf(geom,left,top),z=viewToPdf(geom,left+box.width,top+box.height),next:[number,number,number,number]=[Math.min(a[0],z[0]),Math.min(a[1],z[1]),Math.max(a[0],z[0]),Math.max(a[1],z[1])]
 if(equalRect(next,rect))return operations
 if(equalRect(next,widget.rect))return []
 return stagePdfFormWidgetProperties(model,[],target(selection),{rect:next})
}

export function mountPdfFormCanvas(options:Options):PdfFormCanvasController{
 const {editor,host,pageId,viewport}=options,doc=editor.ownerDocument,sourceSha256=options.model().sourceSha256,abort=new AbortController(),records=new Map<SVGRectElement,PdfFormCanvasSelection>()
 const svg=doc.createElementNS(NS,'svg');svg.setAttribute('class','pdf-form-canvas');svg.setAttribute('width',String(viewport.width));svg.setAttribute('height',String(viewport.height));svg.setAttribute('aria-label','表单控件画布，方向键微调1点，Shift加速为10点')
 let disposed=false,wasConnected=false
 const active=()=>!disposed&&svg.isConnected&&editor.contains(svg)&&options.model().sourceSha256===sourceSha256&&options.current()
 const ownsSelection=()=>options.selected()?.pageId===pageId&&options.selected()?.sourceSha256===sourceSha256
 function clear(){if(ownsSelection())options.select(undefined);for(const rect of records.keys()){rect.classList.remove('is-selected');rect.setAttribute('aria-pressed','false')}}
 function read(selection:PdfFormCanvasSelection){return currentWidget(options.model(),options.operations(),selection)}
 function paint(rect:SVGRectElement,value:readonly number[]){const a=viewport.convertToViewportPoint(value[0],value[1]),b=viewport.convertToViewportPoint(value[2],value[3]);for(const[k,v]of Object.entries({x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),width:Math.abs(b[0]-a[0]),height:Math.abs(b[1]-a[1])}))rect.setAttribute(k,String(v))}
 function sync(){
  if(disposed)return false
  if(!svg.isConnected){if(wasConnected)clear();return false}wasConnected=true
  if(!active())clear()
  let selectedFound=false
  for(const[rect,selection]of records){let enabled=active(),geometry:readonly number[]|undefined
   try{geometry=read(selection).rect}catch{enabled=false}
   if(geometry)paint(rect,geometry)
   const selected=enabled&&same(options.selected(),selection);selectedFound||=selected;rect.classList.toggle('is-selected',selected);rect.classList.toggle('is-disabled',!enabled);rect.setAttribute('aria-pressed',String(selected));rect.setAttribute('aria-disabled',String(!enabled));rect.setAttribute('tabindex',enabled?'0':'-1')
  }
  if(ownsSelection()&&!selectedFound)clear()
  return true
 }
 function choose(event:Event,rect:SVGRectElement,selection:PdfFormCanvasSelection){
  if(!active()||event.defaultPrevented)return
  try{read(selection)}catch{return}
  event.preventDefault();event.stopPropagation();options.select(selection);sync();rect.focus()
 }
 for(const widget of options.model().formDesignWidgets??[]){
  const page=options.model().pages.find((p,i)=>(p.index??i)===widget.pageIndex)
  if(!page||page.pageId!==pageId||!widget.designEditable||(options.model().formDesignWidgets??[]).filter(w=>w.fieldName===widget.fieldName).length!==1)continue
  const selection={sourceSha256,pageId,...target({...widget,sourceSha256,pageId})},rect=doc.createElementNS(NS,'rect');records.set(rect,selection);rect.setAttribute('class','pdf-form-canvas-widget');rect.dataset.pdfFormCanvasWidget=widget.widgetIdentity;rect.dataset.pdfFormCanvasWidgetId=widget.widgetId;rect.setAttribute('role','button');rect.setAttribute('tabindex','0');rect.setAttribute('aria-label',widget.fieldName+' 控件 '+widget.widgetId+'（第'+(widget.pageIndex+1)+'页），方向键微调');paint(rect,widget.rect)
  rect.addEventListener('pointerdown',event=>{if(event.button===0&&event.isPrimary!==false)choose(event,rect,selection)},{signal:abort.signal})
  rect.addEventListener('keydown',event=>{if(event.isComposing||event.keyCode===229)return;if(event.key==='Enter'||event.key===' ')choose(event,rect,selection)},{signal:abort.signal});svg.append(rect)
 }
 const blocked='.pdf-ribbon,input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="tablist"],[role="dialog"],dialog,.pdf-form-create-panel,.pdf-form-design-panel,.pdf-form-text-properties-panel,.pdf-form-radio-extension-panel'
 doc.addEventListener('keydown',event=>{
  if(event.defaultPrevented||event.isComposing||event.keyCode===229||event.ctrlKey||event.metaKey||event.altKey||!active()||!ownsSelection())return
  const element=event.target instanceof Element?event.target:undefined
  if([...doc.querySelectorAll('dialog[open],[role="dialog"],[role="alertdialog"]')].some(dialog=>!dialog.closest('[hidden],[aria-hidden="true"]')&&doc.defaultView?.getComputedStyle(dialog).display!=='none'))return
  if(element?.closest(blocked)||element&&!editor.contains(element)&&element!==doc.body&&element!==doc.documentElement)return
  if(event.key==='Escape'){event.preventDefault();clear();return}
  if(!directions[event.key])return
  const selection=options.selected()!;let next:NativeOperation[]
  try{read(selection);next=stagePdfFormWidgetNudge(options.model(),options.operations(),selection,event.key,event.shiftKey)}catch{return}
  event.preventDefault();event.stopPropagation()
  try{if(JSON.stringify(next)!==JSON.stringify(options.operations()))options.commit(next);sync()}catch(error){options.error(error)}
 },{signal:abort.signal})
 for(const type of ['pointerdown','focusin'])doc.addEventListener(type,event=>{
  if(!ownsSelection())return
  const node=event.target as Node|null
  if(node&&!editor.contains(node)&&(type==='pointerdown'||node!==doc.body&&node!==doc.documentElement))clear()
 },{capture:true,signal:abort.signal})
 host.append(svg);if(svg.isConnected)sync()
 return {sync,clear,dispose(){if(disposed)return;disposed=true;abort.abort();svg.remove();records.clear()}}
}
