import {afterEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {mountPdfFormDesignCanvas,type PdfFormDesignSelection} from './pdf-form-design-canvas'
import type {PdfFormCreateModel} from './pdf-form-create'
import {NativeDraft} from './native-draft'
import {PdfFormClipboard} from './pdf-form-clipboard'
const sha='a'.repeat(64),pageId='p',controllers:ReturnType<typeof mountPdfFormDesignCanvas>[]=[]
const widget=(i:number)=>({fieldName:'field'+i,widgetId:(7+i)+'R',widgetIdentity:String(i+1).repeat(64),expectedWidgetSha256:'b'.repeat(64),pageIndex:0,rect:[20+i*100,40,80+i*100,60]as [number,number,number,number],designEditable:true,removable:true,removalReason:null,fieldKind:'text',required:false})
afterEach(()=>{act(()=>controllers.splice(0).forEach(c=>c.dispose()));document.body.replaceChildren();vi.restoreAllMocks()})
function setup(rotation=0){
 Object.defineProperty(HTMLElement.prototype,'setPointerCapture',{value:()=>{},configurable:true});(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true
 const editor=document.createElement('div'),host=document.createElement('div');editor.append(host);document.body.append(editor)
 let enabled=true,preview=false,tool:null|'text'|'signature'=null;const model:PdfFormCreateModel={sourceSha256:sha,pages:[{pageId,index:0,rotation,cropBox:{x:0,y:0,width:300,height:400}}],capabilities:{editFormWidget:true,createFormField:true},formDesignWidgets:[widget(0),widget(1)]},selection:PdfFormDesignSelection={ids:new Set()},errors:unknown[]=[],draft=new NativeDraft({documentId:'canvas',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 const clipboard=new PdfFormClipboard(sha)
 let controller:ReturnType<typeof mountPdfFormDesignCanvas>;act(()=>{controller=mountPdfFormDesignCanvas({editor,host,pageId,scale:1,model:()=>model,operations:()=>draft.operations,current:()=>enabled,selection,clipboard,pasteTarget:()=>!selection.pageId||selection.pageId===pageId,select(){},commit(operations){draft.setOperations(operations)},error(error){errors.push(error)},preview:()=>preview,tool:()=>tool,created(keep){if(!keep)tool=null},cancelled(){tool=null},fieldValues:()=>[{name:'field0',value:'Original'}]})});controllers.push(controller!)
 return {host,editor,draft,model,selection,clipboard,errors,controller:controller!,arm(kind:'text'|'signature'='text'){tool=kind;act(()=>controller.sync())},field(i=0){return host.querySelector<HTMLElement>('[data-field-id="widget:'+(7+i)+'R"]')!},disable(){enabled=false;act(()=>controller.sync())},preview(){preview=true;act(()=>controller.sync())}}
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
it('renders and edits multiple pending fields without clearing unrelated creations',()=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false},second={...first,fieldName:'Second',rect:[30,140,150,164]}
 f.draft.setOperations([first,second]);act(()=>f.controller.sync())
 const target=f.host.querySelector('[data-field-id="pending:Second"]')!;expect(target).not.toBeNull();key(target,'Enter');key(target,'ArrowRight')
 expect(f.draft.operations[0]).toEqual(first);expect(f.draft.operations[1]!.rect).toEqual([31,140,151,164])
 const card=document.querySelector('.pdf-formdesign-props')!,remove=[...card.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='删除字段')!
 act(()=>remove.click());expect(f.draft.operations).toEqual([first]);expect(f.errors).toEqual([])
})
it('Ctrl keeps the creation tool and a second placement appends a distinct field',()=>{
 const f=setup();f.arm();let layer=f.host.querySelector('.pdf-formdesign-layer')!
 pointer(layer,'pointerdown',30,100,{ctrlKey:true});pointer(layer,'pointerup',30,100,{ctrlKey:true})
 const first=f.draft.operations[0];layer=f.host.querySelector('.pdf-formdesign-layer')!
 pointer(layer,'pointerdown',30,180);pointer(layer,'pointerup',30,180)
 expect(f.draft.operations).toHaveLength(2);expect(f.draft.operations[0]).toEqual(first);expect(f.draft.operations[1]).toMatchObject({fieldName:'Field2',fieldKind:'text'});expect(f.errors).toEqual([])
})

it('pending field clipboard shortcuts duplicate and paste without hijacking inputs or IME',()=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false,value:'Alice'}
 f.draft.setOperations([first]);act(()=>f.controller.sync());const original=f.host.querySelector('[data-field-id="pending:First"]')!
 key(original,'Enter');key(original,'c',{ctrlKey:true});expect(f.draft.operations).toHaveLength(1)
 key(original,'d',{ctrlKey:true});expect(f.draft.operations).toHaveLength(2);expect(f.draft.operations[1]).toMatchObject({fieldName:'First_copy1',value:'Alice'})
 const copy=f.host.querySelector('[data-field-id="pending:First_copy1"]')!;key(copy,'v',{ctrlKey:true});expect(f.draft.operations).toHaveLength(3);expect(f.draft.operations[2]!.fieldName).toBe('First_copy2')
 const input=document.querySelector<HTMLInputElement>('.pdf-formdesign-props input')!,before=f.draft.operations;key(input,'d',{ctrlKey:true});key(copy,'d',{ctrlKey:true,isComposing:true});expect(f.draft.operations).toEqual(before);expect(f.errors).toEqual([])
})
it('context clipboard actions reject detached old menu callbacks after the draft changes',()=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false}
 f.draft.setOperations([first]);act(()=>f.controller.sync());const node=f.host.querySelector('[data-field-id="pending:First"]')!
 pointer(node,'contextmenu',40,190)
 const duplicate=[...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(button=>button.textContent==='重复字段')!;expect(duplicate).not.toBeUndefined()
 f.draft.setOperations([{...first,fieldName:'Changed'}]);act(()=>duplicate.click());expect(f.draft.operations).toEqual([{...first,fieldName:'Changed'}])
})
it.each(['','plaintext-only','true'])('clipboard commands leave contenteditable=%s inputs untouched',value=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false}
 f.draft.setOperations([first]);act(()=>f.controller.sync());key(f.host.querySelector('[data-field-id="pending:First"]')!,'Enter')
 const input=f.editor.appendChild(document.createElement('div'));input.setAttribute('contenteditable',value);const child=input.appendChild(document.createElement('span'));key(child,'d',{ctrlKey:true});expect(f.draft.operations).toEqual([first])
})
it('pending context deletion removes the selected creation rather than opening a source-field action',()=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false}
 f.draft.setOperations([first]);act(()=>f.controller.sync());pointer(f.host.querySelector('[data-field-id="pending:First"]')!,'contextmenu',40,190)
 const remove=[...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(button=>button.textContent==='删除字段')!;expect(remove.disabled).toBe(false);act(()=>remove.click());expect(f.draft.operations).toEqual([])
})

it('two mounted pages share one clipboard and only the owning page commits a paste shortcut',()=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false,value:'Alice'}
 f.model.pages.push({pageId:'q',index:1,rotation:0,cropBox:{x:10,y:20,width:300,height:400}})
 f.draft.setOperations([first]);act(()=>f.controller.sync());const original=f.host.querySelector('[data-field-id="pending:First"]')!;key(original,'Enter');key(original,'c',{ctrlKey:true})
 const second=f.editor.appendChild(document.createElement('div')),commit=vi.fn(operations=>f.draft.setOperations(operations));let controller:ReturnType<typeof mountPdfFormDesignCanvas>
 act(()=>{controller=mountPdfFormDesignCanvas({editor:f.editor,host:second,pageId:'q',scale:1,model:()=>f.model,operations:()=>f.draft.operations,current:()=>true,selection:f.selection,clipboard:f.clipboard,select(){},commit,error:error=>f.errors.push(error)})});controllers.push(controller!)
 f.selection.pageId='q';f.selection.ids.clear();act(()=>controller.sync());key(second,'v',{ctrlKey:true})
 expect(commit).toHaveBeenCalledTimes(1);expect(f.draft.operations).toHaveLength(2);expect(f.draft.operations[1]).toMatchObject({fieldName:'First_copy1',pageId:'q',value:'Alice',rect:[50,210,170,234]});expect(f.errors).toEqual([])
})
it('pastes to the active canvas after the field selection is cleared',()=>{
 const f=setup(),first={kind:'createFormField',sourceSha256:sha,pageId,fieldName:'First',fieldKind:'text',rect:[30,200,150,224],required:false}
 f.draft.setOperations([first]);act(()=>f.controller.sync());const original=f.host.querySelector('[data-field-id="pending:First"]')!;key(original,'Enter');key(original,'c',{ctrlKey:true});act(()=>f.controller.clear());key(f.editor,'v',{ctrlKey:true})
 expect(f.draft.operations).toHaveLength(2);expect(f.draft.operations[1]!.fieldName).toBe('First_copy1')
})
it('duplicates a source widget through keyboard and context menu without exposing lossy pending properties',()=>{
 const f=setup();f.model.formDesignWidgets![0]!.copyEditable=true;act(()=>f.controller.sync());key(f.field(),'Enter');key(f.field(),'c',{ctrlKey:true});expect(f.clipboard.hasContent).toBe(true);key(f.field(),'d',{ctrlKey:true})
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({kind:'createFormField',fieldName:'field0_copy1',copyFrom:{fieldName:'field0',widgetId:'7R'}})
 const copy=f.host.querySelector('[data-field-id="pending:field0_copy1"]')!;expect(copy).not.toBeNull();expect(document.querySelector('.pdf-formdesign-props input')).toBeNull();expect(document.querySelector('.pdf-formdesign-props')!.textContent).toContain('保存后')
 key(copy,'ArrowRight');expect(f.draft.operations[0]!.rect).toEqual([31,30,91,50]);expect(f.errors).toEqual([])
 const handle=f.host.querySelector('.pdf-formdesign-handle.is-e')!;pointer(handle,'pointerdown',90,360);pointer(handle,'pointermove',100,360,{altKey:true});pointer(handle,'pointerup',100,360);expect(f.draft.operations[0]!.rect).toEqual([31,30,91,50]);expect(f.errors.length).toBe(1)
 f.draft.undo();act(()=>f.controller.sync());pointer(f.field(),'contextmenu',40,350);const duplicate=[...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(b=>b.textContent==='重复字段')!;expect(duplicate.disabled).toBe(false);act(()=>duplicate.click());expect(f.draft.operations).toHaveLength(2)
})
it('source date context duplication uses its original identity and keeps copied properties read only',()=>{
 const f=setup();Object.assign(f.model.formDesignWidgets![0]!,{copyEditable:true,fieldKind:'date',dateFormat:'dd/mm/yyyy',required:true});act(()=>f.controller.sync());pointer(f.field(),'contextmenu',40,350)
 const duplicate=[...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(button=>button.textContent==='重复字段')!;expect(duplicate.disabled).toBe(false);act(()=>duplicate.click())
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({fieldKind:'date',required:true,copyFrom:{fieldName:'field0',widgetId:'7R'}});expect(document.querySelector('.pdf-formdesign-props input')).toBeNull();expect(f.errors).toEqual([])
})
it('copying any source radio member duplicates its whole field and copied movement and deletion remain atomic',()=>{
 const f=setup();f.model.formDesignWidgets=f.model.formDesignWidgets!.map((w,i)=>({...w,fieldName:'Answer',fieldKind:'radio',required:true,copyEditable:true,radioRequiredEditable:true,radioOptions:['Yes','No'],radioValue:'No',radioChecked:i===1}));act(()=>f.controller.sync())
 key(f.field(1),'Enter');key(f.field(1),'d',{ctrlKey:true});expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({fieldKind:'radio',fieldName:'Answer_copy1',copyFrom:{widgetId:'7R'}});expect((f.draft.operations[0]!.radioWidgets as any[])).toHaveLength(2)
 key(f.editor,'ArrowRight');expect((f.draft.operations[0]!.radioWidgets as any[]).map(row=>row.rect)).toEqual([[31,30,91,50],[131,30,191,50]])
 const second=f.host.querySelector('[data-field-id="pending:Answer_copy1:1"]')!;key(second,'Enter');expect(document.querySelector('.pdf-formdesign-props')!.textContent).toContain('整组');expect(document.querySelector('.pdf-formdesign-props input')).toBeNull();key(second,'ArrowDown');expect((f.draft.operations[0]!.radioWidgets as any[]).map(row=>row.rect)).toEqual([[31,29,91,49],[131,29,191,49]])
 const remove=[...document.querySelectorAll<HTMLButtonElement>('.pdf-formdesign-props button')].find(button=>button.textContent==='删除整组字段')!;expect(remove).not.toBeUndefined();act(()=>remove.click());expect(f.draft.operations).toEqual([]);f.draft.undo();act(()=>f.controller.sync());expect(f.draft.operations).toHaveLength(1);expect(f.errors).toEqual([])
})
it('duplicates an empty signature source with a truthful Chinese placeholder card and native move undo',()=>{
 const f=setup();Object.assign(f.model.formDesignWidgets![0]!,{fieldKind:'signature',copyEditable:true});act(()=>f.controller.sync());key(f.field(),'Enter');key(f.field(),'d',{ctrlKey:true});expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({fieldKind:'signature',copyFrom:{widgetId:'7R'}})
 const card=document.querySelector('.pdf-formdesign-props')!;expect(card.textContent).toContain('空签名字段');expect(card.textContent).not.toContain('字体');expect(card.querySelector('input')).toBeNull();const clone=f.host.querySelector('[data-field-id="pending:field0_copy1"]')!;key(clone,'ArrowRight');expect(f.draft.operations[0]!.rect).toEqual([31,30,91,50]);f.draft.undo();act(()=>f.controller.sync());expect(f.draft.operations[0]!.rect).toEqual([30,30,90,50]);expect(f.errors).toEqual([])
})
it('duplicates from a non-root source page then moves only that page and deletes the complete multipage group',()=>{
 const f=setup();f.model.pages.push({pageId:'q',index:1,rotation:0,cropBox:{x:20,y:20,width:300,height:400}});f.model.formDesignWidgets=f.model.formDesignWidgets!.map((w,i)=>({...w,fieldName:'Answer',fieldKind:'radio',required:true,copyEditable:true,radioOptions:['Yes','No'],radioValue:'No',radioChecked:i===1,pageIndex:i}));act(()=>f.controller.sync());const second=f.editor.appendChild(document.createElement('div'));let controller:ReturnType<typeof mountPdfFormDesignCanvas>;act(()=>{controller=mountPdfFormDesignCanvas({editor:f.editor,host:second,pageId:'q',scale:1,model:()=>f.model,operations:()=>f.draft.operations,current:()=>true,selection:f.selection,clipboard:f.clipboard,select(){},commit:ops=>f.draft.setOperations(ops),error:error=>f.errors.push(error)})});controllers.push(controller!)
 const source=second.querySelector('[data-field-id="widget:8R"]')!;key(source,'Enter');key(source,'d',{ctrlKey:true});expect(f.draft.operations).toHaveLength(1);const before=(f.draft.operations[0]!.radioWidgets as any[]).map(row=>structuredClone(row.rect));const member=second.querySelector('[data-field-id="pending:Answer_copy1:1"]')!;key(member,'Enter');expect(document.querySelector('.pdf-formdesign-props')!.textContent).toContain('当前页');key(member,'ArrowRight');expect((f.draft.operations[0]!.radioWidgets as any[]).map(row=>row.rect)).toEqual([before[0],before[1].map((v:number,i:number)=>v+(i%2===0?1:0))])
 const remove=[...document.querySelectorAll<HTMLButtonElement>('.pdf-formdesign-props button')].find(button=>button.textContent==='删除整组字段')!;act(()=>remove.click());expect(f.draft.operations).toEqual([]);f.draft.undo();act(()=>{f.controller.sync();controller.sync()});expect(f.host.querySelector('[data-field-id="pending:Answer_copy1:0"]')).not.toBeNull();expect(second.querySelector('[data-field-id="pending:Answer_copy1:1"]')).not.toBeNull();expect(f.errors).toEqual([])
})
