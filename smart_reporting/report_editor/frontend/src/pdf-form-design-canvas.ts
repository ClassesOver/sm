/** Fixed PC FormDesignLayer host. Browser geometry never supplies native PDF dictionaries. */
import {createElement,Fragment} from 'react'
import {createRoot} from 'react-dom/client'
import {flushSync,createPortal} from 'react-dom'
import {FormDesignLayer,FormFieldProps,type DesignField,type FormDesignTool} from './pdf-form-design-layer-source'
import {geomDispSize,pdfRectToCss,viewToPdf} from './genoffice-pdf-annotations'
import {stagePdfFormWidgetRects,stagePdfFormCreation,stagePdfFormWidgetProperties,type PdfFormWidgetRectChange,type PdfFormCreateModel} from './pdf-form-create'
import type {NativeOperation} from './native-draft'
import './pdf-form-design-layer.css'
export interface PdfFormDesignSelection {pageId?:string;ids:Set<string>}
interface Options {
 editor:HTMLElement;host:HTMLElement;pageId:string;scale:number
 model():PdfFormCreateModel;operations():NativeOperation[];current():boolean
 selection:PdfFormDesignSelection;select():void
 commit(operations:NativeOperation[]):void;error(error:unknown):void
 tool?():FormDesignTool|null;created?(keep:boolean):void;cancelled?():void
 preview?():boolean
 fieldValues?():{name:string;value:string|boolean|null;options?:string[]}[]
 properties?():void;remove?():void
}
export function mountPdfFormDesignCanvas(options:Options){
 const owner=options.host.ownerDocument,host=owner.createElement('div');host.className='pdf-formdesign-host';options.host.append(host)
 const propertyHost=owner.createElement('div');propertyHost.className='pdf-formdesign-property-host';owner.body.append(propertyHost)
 const root=createRoot(host),abort=new AbortController(),source=options.model().sourceSha256,selection=options.selection
 let disposed=false,connected=false,gesture:string|undefined,epoch=0,menu:HTMLElement|undefined
 const snapshot=()=>JSON.stringify([options.model(),options.operations()])
 const active=()=>!disposed&&host.isConnected&&options.editor.contains(host)&&source===options.model().sourceSha256&&options.current()
 const owns=()=>selection.pageId===options.pageId
 const page=()=>options.model().pages.find(p=>p.pageId===options.pageId)
 const geom=()=>{const p=page();if(!p)throw Error('字段页面身份已变化');return {pw:p.cropBox.width,ph:p.cropBox.height,x0:p.cropBox.x,y0:p.cropBox.y,rot:p.rotation??0}}
 function fields():DesignField[]{
  const m=options.model(),p=page(),operations=options.operations();if(!p)return []
  if(operations.length&&!(operations.length===1&&['editFormWidgetRects','createFormField'].includes(operations[0].kind)))return []
  const op=operations[0],changes=op?.kind==='editFormWidgetRects'?op.changes as PdfFormWidgetRectChange[]:[]
  if(changes.length)stagePdfFormWidgetRects(m,[],changes)
  const result:DesignField[]=(m.formDesignWidgets??[]).filter(w=>w.designEditable&&w.pageIndex===(p.index??m.pages.indexOf(p))).map(w=>({id:'widget:'+w.widgetId,kind:(w.fieldKind??'unknown')as DesignField['kind'],name:w.fieldName,pageIndex:w.pageIndex,rect:changes.find(c=>c.widgetId===w.widgetId)?.rect??w.rect,required:w.required??false,existing:true}))
  if(op?.kind==='createFormField'&&op.fieldKind==='radio'){
   const {kind,sourceSha256,...input}=op;stagePdfFormCreation(m,[],input as unknown as Parameters<typeof stagePdfFormCreation>[2])
   for(const [i,row]of (op.radioWidgets as {pageId:string;rect:DesignField['rect'];exportValue:string;checked?:boolean}[]).entries())if(row.pageId===options.pageId)result.push({id:'pending:'+op.fieldName+':'+i,kind:'radio',name:String(op.fieldName),pageIndex:p.index??m.pages.indexOf(p),rect:row.rect,required:op.required===true,existing:false,pending:{input:{name:String(op.fieldName),kind:'radio',pageIndex:p.index??m.pages.indexOf(p),rect:row.rect,required:op.required===true,exportValue:row.exportValue,checked:row.checked??false}}})
  }else if(op?.kind==='createFormField'&&op.pageId===options.pageId){
   const {kind,sourceSha256,...input}=op;stagePdfFormCreation(m,[],input as unknown as Parameters<typeof stagePdfFormCreation>[2])
   result.push({id:'pending:'+op.fieldName,kind:(op.fieldKind==='date'?'text':op.fieldKind)as DesignField['kind'],name:String(op.fieldName),pageIndex:p.index??m.pages.indexOf(p),rect:op.rect as DesignField['rect'],required:op.required===true,existing:false,pending:{input:{...input,name:String(op.fieldName),kind:op.fieldKind==='date'?'text':op.fieldKind,pageIndex:p.index??m.pages.indexOf(p)}as NonNullable<DesignField['pending']>['input']}})
  }
  return result
 }
 function closeMenu(){menu?.remove();menu=undefined}
 function clear(){if(owns()){selection.ids.clear();selection.pageId=undefined}gesture=undefined;epoch++;closeMenu()}
 function commitRects(changes:{id:string;rect:DesignField['rect']}[]){
  try{
   if(!active()||options.preview?.()||gesture!==snapshot())throw Error('拖动期间来源、草稿或编辑状态已变化，请重新选择控件')
   const m=options.model(),op=options.operations()[0]
   if(op?.kind==='createFormField'){
    const {kind,sourceSha256,...input}=op
    if(op.fieldKind==='radio'){
     const rows=structuredClone(op.radioWidgets as {pageId:string;rect:DesignField['rect'];exportValue:string;checked?:boolean}[])
     for(const c of changes){const index=rows.findIndex((_,i)=>c.id==='pending:'+op.fieldName+':'+i);if(index<0||rows[index].pageId!==options.pageId)throw Error('单选选项或页面身份已变化');rows[index].rect=c.rect}
     options.commit(stagePdfFormCreation(m,[],{...input,radioWidgets:rows,pageId:rows[0].pageId,rect:rows[0].rect}as Parameters<typeof stagePdfFormCreation>[2]))
    }else{
     if(changes.length!==1||changes[0].id!=='pending:'+op.fieldName)throw Error('新建字段须单独调整并保存')
     options.commit(stagePdfFormCreation(m,[],{...input,rect:changes[0].rect}as Parameters<typeof stagePdfFormCreation>[2]))
    }
   }else{
    const next=changes.map(c=>{const w=m.formDesignWidgets?.find(w=>'widget:'+w.widgetId===c.id);if(!w)throw Error('字段控件身份已变化');return {fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256,rect:c.rect}})
    options.commit(stagePdfFormWidgetRects(m,options.operations(),next))
   }
  }catch(error){options.error(error)}finally{gesture=undefined;sync()}
 }
 function sync(){
  if(disposed)return false;if(!host.isConnected){if(connected)clear();return false}connected=true
  let values:DesignField[]=[];try{values=fields()}catch{}
  const designing=active(),preview=!!options.preview?.()&&designing
  if(preview)values=values.map(f=>{if(!f.existing)return f;const value=options.fieldValues?.().find(v=>v.name===f.name),w=options.model().formDesignWidgets?.find(w=>'widget:'+w.widgetId===f.id);return {...f,existing:false,pending:{input:{name:f.name,kind:f.kind==='unknown'?'text':f.kind,pageIndex:f.pageIndex,rect:f.rect,required:f.required,value:typeof value?.value==='string'?value.value:undefined,checked:f.kind==='radio'?w?.radioChecked===true:value?.value===true,options:value?.options,dateFormat:w?.dateFormat,multiLine:w?.textProperties?.multiLine}}}})
  if(!designing&&owns())clear()
  if(owns())for(const id of selection.ids)if(!values.some(f=>f.id===id))selection.ids.delete(id)
  let g;try{g=geom()}catch{return false}const size=geomDispSize(g)
  const selected=designing&&!preview&&owns()&&selection.ids.size===1?values.find(f=>selection.ids.has(f.id)):undefined,keyAtRender=snapshot()
  const anchor=selected?pdfRectToCss(g,selected.rect,options.scale):{left:0,top:0,width:0,height:0},origin=host.getBoundingClientRect(),windowWidth=owner.defaultView?.innerWidth??800,windowHeight=owner.defaultView?.innerHeight??600
  const props=selected?createElement(FormFieldProps,{key:selected.id,field:selected,isNew:!selected.existing,style:{left:Math.max(8,Math.min(origin.left+anchor.left,windowWidth-Math.min(320,windowWidth-16)-8)),top:Math.max(8,Math.min(origin.top+anchor.top+anchor.height+8,windowHeight-(selected.existing?150:280)-8))},labels:{required:'必填',multiLine:'多行',defaultValue:'默认值',defaultChecked:'默认勾选',remove:'删除字段',done:'完成',cancel:selected.kind==='radio'&&!selected.existing?'取消新建组':'取消',existingHint:'已有控件：按真实来源身份修改；几何调整与其他属性须分开保存',exportValue:'导出值',radioGroupHint:'同名单选字段属于一组',options:'选项（每行一个）',dateFormat:'日期格式'},
   onPatch(patch){try{if(!active()||keyAtRender!==snapshot())throw Error('字段来源或草稿已变化');if(selected.existing){if(Object.keys(patch).some(k=>k!=='required'))throw Error('已有字段属性请使用字段设置');const w=options.model().formDesignWidgets!.find(w=>'widget:'+w.widgetId===selected.id)!;options.commit(stagePdfFormWidgetProperties(options.model(),options.operations(),{fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256},{required:patch.required}))}else{const op=options.operations()[0],{kind,sourceSha256,...input}=op;if(op.fieldKind==='radio'){if(Object.keys(patch).some(k=>!['required','exportValue','checked'].includes(k)))throw Error('单选选项属性无效');const rows=structuredClone(op.radioWidgets as {pageId:string;rect:DesignField['rect'];exportValue:string;checked?:boolean}[]),index=rows.findIndex((_,i)=>selected.id==='pending:'+op.fieldName+':'+i);if(index<0)throw Error('单选选项身份已变化');if(patch.exportValue!==undefined)rows[index].exportValue=patch.exportValue;if(patch.checked!==undefined){if(patch.checked)rows.forEach(row=>{row.checked=false});rows[index].checked=patch.checked}options.commit(stagePdfFormCreation(options.model(),[],{...input,...(patch.required!==undefined?{required:patch.required}:{}),radioWidgets:rows}as Parameters<typeof stagePdfFormCreation>[2]))}else options.commit(stagePdfFormCreation(options.model(),[],{...input,...patch,fieldKind:op.fieldKind,pageId:op.pageId,fieldName:op.fieldName,rect:op.rect}as Parameters<typeof stagePdfFormCreation>[2]))}sync();return true}catch(error){options.error(error);return false}},
   onDelete(){if(!active()||keyAtRender!==snapshot())return;if(selected.existing)options.remove?.();else{const op=options.operations()[0];if(op.fieldKind==='radio'){const rows=(op.radioWidgets as {pageId:string;rect:DesignField['rect'];exportValue:string;checked?:boolean}[]).filter((_,i)=>selected.id!=='pending:'+op.fieldName+':'+i);if(rows.length<2){options.error(Error('单选组至少保留两个选项；可取消整组新建'));return}const {kind,sourceSha256,...input}=op;options.commit(stagePdfFormCreation(options.model(),[],{...input,radioWidgets:rows,pageId:rows[0].pageId,rect:rows[0].rect}as Parameters<typeof stagePdfFormCreation>[2]))}else options.commit([]);clear();options.select();sync()}},
   onDone(){clear();options.select();sync()},onCancel(){if(!active()||keyAtRender!==snapshot())return;if(!selected.existing)options.commit([]);clear();options.select();sync()},
  }):null
  flushSync(()=>root.render(createElement(Fragment,null,createElement(FormDesignLayer,{key:epoch,designing,preview,tool:designing&&!preview?options.tool?.()??null:null,geom:g,scale:options.scale,pageWidth:size.width,pageHeight:size.height,fields:values,selectedIds:owns()?selection.ids:new Set<string>(),
   onSelect(ids,mode){if(!active()||preview)return;if(!owns()||mode==='replace')selection.ids.clear();selection.pageId=options.pageId;for(const id of ids){if(mode==='toggle'&&selection.ids.has(id))selection.ids.delete(id);else selection.ids.add(id)}options.select();sync()},
   onRects:commitRects,
   onCreate(tool,rect,keep){try{if(!active()||preview||gesture!==snapshot()||options.operations().length)throw Error('新建字段须单独保存，请先保存或撤销其他修改');if(tool==='radio')throw Error('该字段请使用已验证的字段设置入口');const m=options.model();let n=1;while(m.formDesignWidgets?.some(w=>w.fieldName==='Field'+n))n++;const fieldKind=tool as 'text'|'date'|'choice'|'checkbox'|'signature',next=stagePdfFormCreation(m,[],{pageId:options.pageId,fieldName:'Field'+n,fieldKind,rect,required:false,...(tool==='date'?{dateFormat:'yyyy-mm-dd' as const}:{}),...(tool==='choice'?{options:['One','Two']}: {})});options.commit(next);selection.pageId=options.pageId;selection.ids=new Set(['pending:Field'+n]);options.created?.(keep)}catch(error){options.error(error)}finally{gesture=undefined;sync()}},
   onContextMenu(event,id){if(!active()||preview)return;closeMenu();if(id&&!selection.ids.has(id)){selection.pageId=options.pageId;selection.ids=new Set([id]);options.select();sync()}menu=owner.createElement('div');menu.className='pdf-formdesign-context';menu.setAttribute('role','menu');menu.setAttribute('aria-label','表单控件');for(const[label,action]of [['字段属性',options.properties],['删除字段',options.remove]]as const){const b=owner.createElement('button');b.type='button';b.textContent=label;b.setAttribute('role','menuitem');b.disabled=!id||!action;b.onclick=()=>{closeMenu();action?.()};menu.append(b)}menu.style.left=Math.max(4,Math.min(event.clientX,(owner.defaultView?.innerWidth??500)-140))+'px';menu.style.top=Math.max(4,Math.min(event.clientY,(owner.defaultView?.innerHeight??500)-90))+'px';owner.body.append(menu);menu.querySelector('button')?.focus()},
  }),createPortal(props,propertyHost))))
  return true
 }
 host.addEventListener('pointerdown',()=>{if(active())gesture=snapshot()},{capture:true,signal:abort.signal})
 owner.defaultView?.addEventListener('scroll',()=>{if(owns()&&selection.ids.size)sync()},{capture:true,signal:abort.signal})
 owner.defaultView?.addEventListener('resize',()=>{if(owns()&&selection.ids.size)sync()},{signal:abort.signal})
 owner.addEventListener('pointerdown',event=>{if(menu&&!menu.contains(event.target as Node))closeMenu()},{signal:abort.signal})
 owner.addEventListener('keydown',event=>{
  if(event.defaultPrevented||event.isComposing||event.keyCode===229||!active())return
  if(event.key==='Escape'&&(owns()||options.tool?.()||options.preview?.())){event.preventDefault();clear();options.cancelled?.();options.select();sync();return}
  if(!owns()||event.ctrlKey||event.metaKey||event.altKey||options.preview?.())return
  const el=event.target as Element|null;if(el?.closest('input,textarea,select,[contenteditable="true"],.pdf-ribbon,dialog,[role="dialog"],[role="menu"],.pdf-form-create-panel,.pdf-form-design-panel,.pdf-form-text-properties-panel')||el&&!options.editor.contains(el)&&el!==owner.body&&el!==owner.documentElement)return
  if([...owner.querySelectorAll('dialog[open],[role="dialog"],[role="alertdialog"]')].some(d=>!d.closest('[hidden],[aria-hidden="true"]')&&owner.defaultView?.getComputedStyle(d).display!=='none'))return
  const direction=({ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}as Record<string,number[]>)[event.key]
  if(!direction||!selection.ids.size)return
  try{const g=geom(),size=geomDispSize(g),values=fields().filter(f=>selection.ids.has(f.id)),step=event.shiftKey?10:1,changes=values.map(f=>{const b=pdfRectToCss(g,f.rect,1),left=Math.min(Math.max(b.left+direction[0]*step,0),size.width-b.width),top=Math.min(Math.max(b.top+direction[1]*step,0),size.height-b.height),a=viewToPdf(g,left,top),z=viewToPdf(g,left+b.width,top+b.height);return {id:f.id,rect:[Math.min(a[0],z[0]),Math.min(a[1],z[1]),Math.max(a[0],z[0]),Math.max(a[1],z[1])]as DesignField['rect']}});event.preventDefault();gesture=snapshot();commitRects(changes)}catch(error){options.error(error)}
 },{signal:abort.signal})
 sync();return {sync,clear,dispose(){if(disposed)return;disposed=true;abort.abort();closeMenu();root.unmount();propertyHost.remove();host.remove()}}
}
