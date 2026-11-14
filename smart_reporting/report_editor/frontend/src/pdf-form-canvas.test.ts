import {afterEach,expect,it} from 'vitest'
import {NativeDraft} from './native-draft'
import {mountPdfFormCanvas,stagePdfFormWidgetNudge,type PdfFormCanvasSelection,type PdfFormCanvasController} from './pdf-form-canvas'
import type {PdfFormCreateModel} from './pdf-form-create'
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0',widget={fieldName:'customer',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[20,30,60,50]as[number,number,number,number],required:false,removable:true,removalReason:null,designEditable:true}
const selection:PdfFormCanvasSelection={sourceSha256:sha,pageId,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256}
const controllers:PdfFormCanvasController[]=[]
afterEach(()=>{controllers.forEach(c=>c.dispose());controllers.length=0;document.body.replaceChildren()})
function model(rotation=0):PdfFormCreateModel{return {sourceSha256:sha,pages:[{pageId,index:0,rotation,cropBox:{x:10,y:10,width:200,height:300}}],formDesignWidgets:[structuredClone(widget)],capabilities:{editFormWidget:true}}}
function fixture(rotation=0,scale=1){
 const editor=document.createElement('div'),host=document.createElement('div');editor.append(host);document.body.append(editor);let m=model(rotation),selected:PdfFormCanvasSelection|undefined,enabled=true,errors:unknown[]=[],commits=0
 const draft=new NativeDraft({documentId:'form-canvas',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 const point=(x:number,y:number)=>{x-=10;y-=10;const p=rotation===90?[y,x]:rotation===180?[200-x,y]:rotation===270?[300-y,200-x]:[x,300-y];return p.map(v=>v*scale)}
 const options={editor,host,pageId,viewport:{width:(rotation%180?300:200)*scale,height:(rotation%180?200:300)*scale,convertToViewportPoint:point},model:()=>m,operations:()=>draft.operations,current:()=>enabled&&!draft.saving&&!draft.closed,selected:()=>selected,select(value:PdfFormCanvasSelection|undefined){selected=value},commit(ops:ReturnType<typeof stagePdfFormWidgetNudge>){draft.setOperations(ops);commits++;controller.sync()},error(error:unknown){errors.push(error)}}
 let controller=mountPdfFormCanvas(options);controllers.push(controller)
 return {editor,host,draft,options,get controller(){return controller},get errors(){return errors},get selected(){return selected},get commits(){return commits},get model(){return m},disable(){enabled=false;controller.sync()},enable(){enabled=true;controller.sync()},setModel(value:PdfFormCreateModel){m=value;controller.sync()},remount(){controller.dispose();controller=mountPdfFormCanvas(options);controllers.push(controller)},pick(){const rect=host.querySelector('[data-pdf-form-canvas-widget]')!;rect.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true,cancelable:true,button:0}));controller.sync();return rect}}
}
function key(target:EventTarget,key:string,extra:KeyboardEventInit={}){const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...extra});target.dispatchEvent(event);return event}
it.each(['composing','legacy229','consumed'].flatMap(mode=>['ArrowRight','ArrowUp','Escape'].map(name=>[mode,name])))('keeps selected widget geometry for %s %s',(mode,name)=>{
  const f=fixture(),rect=f.pick()
  if(mode==='consumed')rect.addEventListener('keydown',event=>event.preventDefault(),{once:true})
  const event=key(rect,name,{isComposing:mode==='composing',keyCode:mode==='legacy229'?229:0,shiftKey:name==='ArrowUp'})
  expect(f.selected).toEqual(selection);expect(f.draft.operations).toEqual([]);expect(f.commits).toBe(0);expect(f.errors).toEqual([])
  if(mode!=='consumed')expect(event.defaultPrevented).toBe(false)
  key(rect,'ArrowRight');expect(f.draft.operations[0].rect).toEqual([21,30,61,50]);key(rect,'Escape');expect(f.selected).toBeUndefined()
})
it.each(['composing','legacy229','consumed'].flatMap(mode=>['Enter',' '].map(name=>[mode,name])))('does not select a widget on %s %s',(mode,name)=>{
  const f=fixture(),rect=f.host.querySelector('[data-pdf-form-canvas-widget]')!
  if(mode==='consumed')rect.addEventListener('keydown',event=>event.preventDefault(),{once:true,capture:true})
  const event=key(rect,name,{isComposing:mode==='composing',keyCode:mode==='legacy229'?229:0})
  expect(f.selected).toBeUndefined();expect(rect.getAttribute('aria-pressed')).toBe('false');expect(f.draft.operations).toEqual([])
  if(mode!=='consumed')expect(event.defaultPrevented).toBe(false)
  key(rect,name);expect(f.selected).toEqual(selection);expect(rect.getAttribute('aria-pressed')).toBe('true')
})
it('selects the exact source widget on canvas and accumulates normal/shift keys into one undoable operation',()=>{
 const f=fixture(),rect=f.pick();expect(f.selected).toEqual(selection);expect(rect.classList.contains('is-selected')).toBe(true);expect(key(rect,'ArrowRight').defaultPrevented).toBe(true);key(rect,'ArrowUp',{shiftKey:true});expect(f.draft.operations).toEqual([{kind:'editFormWidget',sourceSha256:sha,fieldName:'customer',widgetId:'7R',widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256,rect:[21,40,61,60]}]);expect(f.commits).toBe(2);f.draft.undo();f.controller.sync();expect(f.draft.operations[0].rect).toEqual([21,30,61,50]);f.draft.redo();f.controller.sync();expect(f.draft.operations[0].rect).toEqual([21,40,61,60]);expect(f.errors).toEqual([])
})
it.each([0,90,180,270])('maps screen directions at rotation %s independently of zoom with a nonzero CropBox',rotation=>{
 const dx=rotation===0?1:rotation===180?-1:0,dy=rotation===90?1:rotation===270?-1:0
 for(const scale of [.5,2]){const f=fixture(rotation,scale),rect=f.pick();key(rect,'ArrowRight');expect(f.draft.operations[0].rect).toEqual([20+dx,30+dy,60+dx,50+dy]);const painted=f.host.querySelector('[data-pdf-form-canvas-widget]')!;expect(Number(painted.getAttribute('width'))).toBe((rotation%180?20:40)*scale)}
})
it('clamps to CropBox, avoids boundary no-ops, and clears a pending rect when arrows return it to source',()=>{
 const m=model(),left={...selection},atEdge={...m,formDesignWidgets:[{...widget,rect:[10,30,50,50]as[number,number,number,number]}]};expect(stagePdfFormWidgetNudge(atEdge,[],left,'ArrowLeft')).toEqual([])
 const right=stagePdfFormWidgetNudge(m,[],selection,'ArrowRight');expect(stagePdfFormWidgetNudge(m,right,selection,'ArrowLeft')).toEqual([]);expect(stagePdfFormWidgetNudge(atEdge,[],selection,'ArrowUp',true)[0].rect).toEqual([10,40,50,60])
})
it('refuses shared fields, forged source/full identity, incompatible drafts and stale pages',()=>{
 for(const key of ['sourceSha256','fieldName','widgetId','widgetIdentity','expectedWidgetSha256','pageId']as const)expect(()=>stagePdfFormWidgetNudge(model(),[],{...selection,[key]:key==='widgetId'?'999R':'f'.repeat(64)},'ArrowRight')).toThrow()
 const shared=model();shared.formDesignWidgets!.push({...widget,widgetId:'8R',widgetIdentity:'d'.repeat(64)});expect(()=>stagePdfFormWidgetNudge(shared,[],selection,'ArrowRight')).toThrow(/单控件|独立/)
 const missing=model();missing.pages=[];expect(()=>stagePdfFormWidgetNudge(missing,[],selection,'ArrowRight')).toThrow(/页面/)
 for(const op of [{kind:'insertText'},{kind:'editFormWidget',...selection,required:true},{kind:'editFormWidget',...selection,rect:widget.rect,unexpected:true}])expect(()=>stagePdfFormWidgetNudge(model(),[op],selection,'ArrowRight')).toThrow()
 const f=fixture();f.draft.setOperations([{kind:'insertText'}]);expect(f.pick()).not.toBeNull();expect(f.selected).toBeUndefined();expect(key(f.editor,'ArrowRight').defaultPrevented).toBe(false)
})
it('lets editable panel dialog ribbon and prevented events keep arrow keys and ignores modifier shortcuts',()=>{
 const f=fixture();f.pick()
 for(const tag of ['input','textarea','select']){const input=document.createElement(tag);f.editor.append(input);expect(key(input,'ArrowRight').defaultPrevented).toBe(false)}
 for(const [tag,attribute,value]of [['div','contenteditable','true'],['div','role','dialog'],['div','role','tablist'],['div','class','pdf-form-create-panel']]as const){const parent=document.createElement(tag),button=document.createElement('button');parent.setAttribute(attribute,value);parent.append(button);f.editor.append(parent);expect(key(button,'ArrowRight').defaultPrevented).toBe(false)}
 const prevented=new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true});prevented.preventDefault();f.editor.dispatchEvent(prevented)
 for(const modifier of ['ctrlKey','metaKey','altKey'])expect(key(f.editor,'ArrowRight',{[modifier]:true}).defaultPrevented).toBe(false)
 expect(f.draft.operations).toEqual([])
})
it('retains selection across render disposal and continues after focus loss while outside activity clears it',()=>{
 const f=fixture(),rect=f.pick();key(rect,'ArrowRight');f.remount();expect(f.selected).toEqual(selection);key(document.body,'ArrowRight');expect(f.draft.operations[0].rect).toEqual([22,30,62,50]);const outside=document.createElement('button');document.body.append(outside);outside.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));expect(f.selected).toBeUndefined();expect(key(document.body,'ArrowRight').defaultPrevented).toBe(false);expect(f.draft.operations[0].rect).toEqual([22,30,62,50])
})
it('escape disabled mode detached host and disposal cannot mutate or retain an active selection',()=>{
 const f=fixture();f.pick();key(f.editor,'Escape');expect(f.selected).toBeUndefined();f.pick();f.disable();expect(key(f.editor,'ArrowRight').defaultPrevented).toBe(false);expect(f.draft.operations).toEqual([])
 const g=fixture();g.pick();g.host.remove();expect(g.controller.sync()).toBe(false);expect(g.selected).toBeUndefined();const h=fixture();h.pick();h.controller.dispose();key(h.editor,'ArrowRight');expect(h.draft.operations).toEqual([])
})

it('keeps an attached inactive controller alive so switching to form design can enable it',()=>{
 const f=fixture();f.disable();expect(f.controller.sync()).toBe(true);expect(key(f.editor,'ArrowRight').defaultPrevented).toBe(false);f.enable();f.pick();key(f.editor,'ArrowRight');expect(f.draft.operations[0].rect).toEqual([21,30,61,50])
})
it('lets focused ribbon command buttons keep arrows and blocks open dialogs even after render focus falls to body',()=>{
 const f=fixture();f.pick();const ribbon=document.createElement('div'),button=document.createElement('button');ribbon.className='pdf-ribbon';ribbon.append(button);f.editor.append(ribbon);expect(key(button,'ArrowRight').defaultPrevented).toBe(false);expect(f.draft.operations).toEqual([])
 const dialog=document.createElement('div');dialog.setAttribute('role','dialog');f.editor.append(dialog);expect(key(document.body,'ArrowRight').defaultPrevented).toBe(false);expect(f.draft.operations).toEqual([]);dialog.hidden=true;key(document.body,'ArrowRight');expect(f.draft.operations[0].rect).toEqual([21,30,61,50])
})
