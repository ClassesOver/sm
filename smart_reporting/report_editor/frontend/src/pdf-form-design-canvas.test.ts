import {afterEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {mountPdfFormDesignCanvas,type PdfFormDesignSelection} from './pdf-form-design-canvas'
import type {PdfFormCreateModel} from './pdf-form-create'
import {NativeDraft} from './native-draft'
const sha='a'.repeat(64),pageId='p',controllers:ReturnType<typeof mountPdfFormDesignCanvas>[]=[]
const widget=(i:number)=>({fieldName:'field'+i,widgetId:(7+i)+'R',widgetIdentity:String(i+1).repeat(64),expectedWidgetSha256:'b'.repeat(64),pageIndex:0,rect:[20+i*100,40,80+i*100,60]as [number,number,number,number],designEditable:true,removable:true,removalReason:null,fieldKind:'text',required:false})
afterEach(()=>{act(()=>controllers.splice(0).forEach(c=>c.dispose()));document.body.replaceChildren();vi.restoreAllMocks()})
function setup(rotation=0){
 Object.defineProperty(HTMLElement.prototype,'setPointerCapture',{value:()=>{},configurable:true});(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true
 const editor=document.createElement('div'),host=document.createElement('div');editor.append(host);document.body.append(editor)
 let enabled=true,preview=false,tool:null|'text'|'signature'=null;const model:PdfFormCreateModel={sourceSha256:sha,pages:[{pageId,index:0,rotation,cropBox:{x:0,y:0,width:300,height:400}}],capabilities:{editFormWidget:true,createFormField:true},formDesignWidgets:[widget(0),widget(1)]},selection:PdfFormDesignSelection={ids:new Set()},errors:unknown[]=[],draft=new NativeDraft({documentId:'canvas',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 let controller:ReturnType<typeof mountPdfFormDesignCanvas>;act(()=>{controller=mountPdfFormDesignCanvas({editor,host,pageId,scale:1,model:()=>model,operations:()=>draft.operations,current:()=>enabled,selection,select(){},commit(operations){draft.setOperations(operations)},error(error){errors.push(error)},preview:()=>preview,tool:()=>tool,created(){tool=null},cancelled(){tool=null},fieldValues:()=>[{name:'field0',value:'Original'}]})});controllers.push(controller!)
 return {host,editor,draft,model,selection,errors,controller:controller!,arm(kind:'text'|'signature'='text'){tool=kind;act(()=>controller.sync())},field(i=0){return host.querySelector<HTMLElement>('[data-field-id="widget:'+(7+i)+'R"]')!},disable(){enabled=false;act(()=>controller.sync())},preview(){preview=true;act(()=>controller.sync())}}
}
function pointer(node:Element,type:string,x:number,y:number,extra:MouseEventInit={}){act(()=>node.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x,clientY:y,...extra})))}
function key(node:Element|Document,key:string,extra:KeyboardEventInit={}){act(()=>node.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...extra})))}
it('uses the fixed-source eight resize handles, modifier multi-selection and one transaction per gesture',()=>{
 const f=setup();pointer(f.field(),'pointerdown',30,350);pointer(f.field(),'pointerup',30,350);expect(f.host.querySelectorAll('.pdf-formdesign-handle')).toHaveLength(8)
 pointer(f.field(1),'pointerdown',130,350,{shiftKey:true});pointer(f.field(1),'pointerup',130,350,{shiftKey:true});expect(f.selection.ids.size).toBe(2);expect(f.host.querySelectorAll('.pdf-formdesign-handle')).toHaveLength(0)
 pointer(f.field(),'pointerdown',30,350);pointer(f.field(),'pointermove',40,340,{altKey:true});expect(f.draft.operations).toEqual([]);pointer(f.field(),'pointerup',40,340)
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0].kind).toBe('editFormWidgetRects');expect((f.draft.operations[0].changes as any[]).map(c=>c.rect)).toEqual([[30,50,90,70],[130,50,190,70]])
 f.draft.undo();act(()=>f.controller.sync());expect(f.draft.operations).toEqual([]);f.draft.redo();act(()=>f.controller.sync());expect(f.errors).toEqual([])
})
it('cancels pointercancel and rejects changed drafts before committing a live drag',()=>{
 const f=setup();pointer(f.field(),'pointerdown',30,350);pointer(f.field(),'pointermove',50,340);pointer(f.field(),'pointercancel',50,340);expect(f.draft.operations).toEqual([])
 pointer(f.field(),'pointerdown',30,350);pointer(f.field(),'pointermove',50,340);f.draft.setOperations([{kind:'insertText'}]);pointer(f.field(),'pointerup',50,340);expect(f.draft.operations).toEqual([{kind:'insertText'}]);expect(String(f.errors[0])).toContain('变化')
})
it.each([0,90,180,270])('moves selected fields with screen-direction keyboard at rotation %s and ignores IME',rotation=>{
 const f=setup(rotation);key(f.field(),'Enter');key(f.field(),'ArrowRight',{isComposing:true});expect(f.draft.operations).toEqual([]);key(f.field(),'ArrowRight');const c=(f.draft.operations[0].changes as any[])[0],dx=rotation===0?1:rotation===180?-1:0,dy=rotation===90?1:rotation===270?-1:0;expect(c.rect).toEqual([20+dx,40+dy,80+dx,60+dy]);key(f.editor,'Escape');expect(f.selection.ids.size).toBe(0)
})
it('provides temporary trial inputs without writing any fill or geometry draft',()=>{
 const f=setup();f.preview();const input=f.host.querySelector<HTMLInputElement>('.pdf-formdesign-preview')!;expect(input).not.toBeNull();expect(input.value).toBe('Original');act(()=>{input.value='Try only';input.dispatchEvent(new Event('change',{bubbles:true}))});key(input,'ArrowRight');expect(f.draft.operations).toEqual([]);expect(f.host.querySelectorAll('.pdf-formdesign-handle')).toHaveLength(0);f.disable();expect(f.draft.operations).toEqual([])
})

it('creates a native pending field from the source canvas and edits its source property card without losing focus',()=>{
 const f=setup();f.arm();const layer=f.host.querySelector('.pdf-formdesign-layer')!;pointer(layer,'pointerdown',30,100);pointer(layer,'pointerup',30,100);expect(f.draft.operations[0]).toMatchObject({kind:'createFormField',fieldName:'Field1',fieldKind:'text',rect:[30,278,190,300]});const card=document.querySelector('.pdf-formdesign-props')!;expect(card).not.toBeNull();const required=Array.from(card.querySelectorAll('label')).find(n=>n.textContent==='必填')!.querySelector('input')!;act(()=>required.click());expect(f.draft.operations[0].required).toBe(true);expect(document.querySelector('.pdf-formdesign-props')).toBe(card);const cancel=Array.from(card.querySelectorAll('button')).find(n=>n.textContent==='取消')!;act(()=>cancel.click());expect(f.draft.operations).toEqual([]);expect(f.errors).toEqual([])
})
it.each(['nw','n','ne','e','se','s','sw','w'])('resizes only the selected widget with the source %s handle',handle=>{
 const f=setup();key(f.field(),'Enter');const h=f.host.querySelector('.pdf-formdesign-handle.is-'+handle)!,dx=handle.includes('w')?-10:handle.includes('e')?10:0,dy=handle.includes('n')?-10:handle.includes('s')?10:0
 pointer(h,'pointerdown',30,350);pointer(h,'pointermove',30+dx,350+dy,{altKey:true});expect(f.draft.operations).toEqual([]);pointer(h,'pointerup',30+dx,350+dy)
 expect((f.draft.operations[0].changes as any[]).map(c=>c.rect)).toEqual([[handle.includes('w')?10:20,handle.includes('s')?30:40,handle.includes('e')?90:80,handle.includes('n')?70:60]]);expect(f.errors).toEqual([])
})
it.each([false,true])('uses source alignment guides and Alt bypass=%s',altKey=>{
 const f=setup();pointer(f.field(),'pointerdown',30,350);pointer(f.field(),'pointermove',72,350,{altKey});expect(f.host.querySelectorAll('.pdf-formdesign-guide').length>0).toBe(!altKey);pointer(f.field(),'pointerup',72,350);expect((f.draft.operations[0].changes as any[])[0].rect).toEqual(altKey?[62,40,122,60]:[60,40,120,60])
})
it('Escape cancels an armed tool and an in-flight first field before any selection exists',()=>{
 const f=setup();f.arm();const layer=f.host.querySelector('.pdf-formdesign-layer')!;pointer(layer,'pointerdown',30,100);pointer(layer,'pointermove',90,130);expect(f.host.querySelector('.is-live')).not.toBeNull();key(f.editor,'Escape');expect(f.host.querySelector('.is-live')).toBeNull();pointer(f.host.querySelector('.pdf-formdesign-layer')!,'pointerup',90,130);expect(f.draft.operations).toEqual([]);expect(f.errors).toEqual([])
})
it('temporary radio preview preserves the individual source widget checked states',()=>{
 const f=setup();f.model.formDesignWidgets=f.model.formDesignWidgets!.map((w,i)=>({...w,fieldName:'answer',fieldKind:'radio',radioValue:'Yes',radioChecked:i===0}));f.preview();expect(Array.from(f.host.querySelectorAll<HTMLInputElement>('input[type=radio]')).map(n=>n.checked)).toEqual([true,false]);expect(f.draft.operations).toEqual([])
})
it('projects pending radio group widgets and edits only the selected option in one creation transaction',()=>{
 const f=setup(),rows=[0,1,2].map(i=>({pageId,rect:[20+i*50,100,40+i*50,120],exportValue:['Yes','No','Maybe'][i],checked:i===1}));f.draft.setOperations([{kind:'createFormField',sourceSha256:sha,pageId,fieldName:'answer',fieldKind:'radio',rect:rows[0].rect,required:false,radioWidgets:rows}]);act(()=>f.controller.sync());const radio=f.host.querySelector('[data-field-id="pending:answer:0"]')!;expect(f.host.querySelectorAll('[data-field-id^="pending:answer:"]')).toHaveLength(3);key(radio,'Enter');key(radio,'ArrowRight');expect((f.draft.operations[0].radioWidgets as any[]).map(w=>w.rect)).toEqual([[21,100,41,120],rows[1].rect,rows[2].rect]);const card=document.querySelector('.pdf-formdesign-props')!,checked=Array.from(card.querySelectorAll('label')).find(n=>n.textContent==='默认勾选')!.querySelector('input')!;act(()=>checked.click());expect((f.draft.operations[0].radioWidgets as any[]).map(w=>w.checked)).toEqual([true,false,false]);const remove=Array.from(card.querySelectorAll('button')).find(n=>n.textContent==='删除字段')!;act(()=>remove.click());expect((f.draft.operations[0].radioWidgets as any[]).map(w=>w.exportValue)).toEqual(['No','Maybe']);expect(f.errors).toEqual([])
})

it('creates the source empty signature card and keeps required undo redo and cancellation native',()=>{
 const f=setup();f.arm('signature');const layer=f.host.querySelector('.pdf-formdesign-layer')!;pointer(layer,'pointerdown',30,100);pointer(layer,'pointerup',30,100);expect(f.draft.operations[0]).toMatchObject({kind:'createFormField',fieldKind:'signature',fieldName:'Field1',rect:[30,256,190,300],required:false});const card=document.querySelector('.pdf-formdesign-props')!;expect(card.querySelectorAll('input')).toHaveLength(1);act(()=>card.querySelector<HTMLInputElement>('input')!.click());expect(f.draft.operations[0].required).toBe(true);f.draft.undo();act(()=>f.controller.sync());expect(f.draft.operations[0].required).toBe(false);f.draft.redo();act(()=>f.controller.sync());expect(f.draft.operations[0].required).toBe(true);const cancel=Array.from(document.querySelectorAll('.pdf-formdesign-props button')).find(n=>n.textContent==='取消')!;act(()=>cancel.dispatchEvent(new MouseEvent('click',{bubbles:true})));expect(f.draft.operations).toEqual([]);expect(f.errors).toEqual([])
})
