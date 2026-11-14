import {afterEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfFormCreatePanel,type PdfFormCreateModel} from './pdf-form-create'
import {bindPdfFormTextPropertiesPanel} from './pdf-form-text-properties'
import {bindPdfRadioExtensionPanel} from './pdf-form-radio-extension'

afterEach(()=>document.body.replaceChildren())
const sha='a'.repeat(64),pageId='p'
const model:PdfFormCreateModel&{capabilities:{appendRadioWidget:boolean;editFormTextProperties:boolean}}={sourceSha256:sha,pages:[{pageId,index:0,cropBox:{x:0,y:0,width:300,height:400}}],capabilities:{createFormField:true,editFormWidget:true,arrangeFormWidgets:true,editFormFieldRequired:true,appendRadioWidget:true,editFormTextProperties:true},formDesignWidgets:[
 {fieldName:'customer',fieldKind:'text',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[30,180,150,204],required:false,removable:true,removalReason:null,designEditable:true,textPropertiesEditable:true,textProperties:{multiLine:false,maxLen:null,textAlignment:'left',fontSize:12,fontName:'Helvetica',valueLength:5}},
 ...['8R','9R'].map((widgetId,index)=>({fieldName:'consent',fieldKind:'radio',widgetId,widgetIdentity:(index?'e':'d').repeat(64),expectedWidgetSha256:'f'.repeat(64),pageIndex:0,rect:[30+index*50,100,50+index*50,120] as [number,number,number,number],required:false,removable:false,removalReason:null,designEditable:true,radioOptions:['Yes','No'],radioValue:'Yes'})),
]}
function fixture(kind:'create'|'text'|'radio'){
 const root=document.createElement('div'),opener=document.createElement('button');document.body.append(root);root.append(opener)
 const draft=new NativeDraft({documentId:kind,revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:vi.fn(),removeItem:vi.fn()})
 let reason:string|null=null
 const options={root,draft,model:()=>model,activePageId:()=>pageId,unavailable:()=>reason,refresh:vi.fn(async()=>{})}
 const panel=kind==='create'?bindPdfFormCreatePanel(options):kind==='text'?bindPdfFormTextPropertiesPanel(options):bindPdfRadioExtensionPanel(options)
 opener.focus();panel.open()
 return {root,opener,draft,panel,block:()=>{reason='只读'},options}
}
for(const kind of ['create','text','radio'] as const){
 it.each(['legacy229','consumed'] as const)(`${kind}: %s Escape preserves panel, focus and draft`,mode=>{
  const f=fixture(kind),control=f.panel.element.querySelector<HTMLInputElement>('input')!;control.focus()
  if(mode==='consumed')control.addEventListener('keydown',event=>event.preventDefault())
  control.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:mode==='legacy229'?229:27,bubbles:true,cancelable:true}))
  expect(f.panel.element.hidden).toBe(false);expect(document.activeElement).toBe(control);expect(f.draft.operations).toEqual([])
 })
 it(`${kind}: desktop header and Escape return focus without stealing external refresh focus`,()=>{
  const f=fixture(kind),close=f.panel.element.querySelector<HTMLButtonElement>('header button')!
  expect(close).not.toBeNull();expect(document.activeElement).toBe(close)
  close.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}));expect(f.panel.element.hidden).toBe(false)
  close.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(f.panel.element.hidden).toBe(true);expect(document.activeElement).toBe(f.opener)
  f.panel.open();f.opener.focus();f.block();f.panel.refresh();expect(document.activeElement).toBe(f.opener);expect(f.draft.operations).toEqual([])
 })
 it(`${kind}: readonly disables native inputs and moves affected focus to close`,()=>{
  const f=fixture(kind),control=f.panel.element.querySelector<HTMLInputElement>('input')!;control.focus();f.block();f.panel.refresh()
  const controls=[...f.panel.element.querySelectorAll('input,select,textarea,fieldset button')]
  expect(controls.length).toBeGreaterThan(0);expect(controls.every(control=>control.matches(':disabled'))).toBe(true)
  expect(document.activeElement).toBe(f.panel.element.querySelector('header button'))
 })
}
it('creation validation keeps all typed values and focused action for correction',async()=>{
 const f=fixture('create'),name=f.root.querySelector<HTMLInputElement>('[data-pdf-form-create-name]')!,size=f.root.querySelector<HTMLInputElement>('[aria-label="字号"]')!
 name.value='invalid..name';size.value='18';const apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-create-apply]')!;apply.focus();apply.click();await Promise.resolve()
 expect(f.draft.operations).toEqual([]);expect(f.panel.element.textContent).toContain('名称')
 expect(f.root.querySelector('[data-pdf-form-create-name]')).toBe(name);expect(name.value).toBe('invalid..name');expect(size.value).toBe('18');expect(document.activeElement).toBe(apply)
})
it('text truncation rejection preserves field choice, values and focus',async()=>{
 const f=fixture('text'),length=f.root.querySelector<HTMLInputElement>('[aria-label="最大长度（0为不限）"]')!,size=f.root.querySelector<HTMLInputElement>('[aria-label="字号"]')!
 length.value='4';size.value='18';const apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-text-properties-apply]')!;apply.focus();apply.click();await Promise.resolve()
 expect(f.panel.element.textContent).toContain('当前文本长度');expect(f.draft.operations).toEqual([])
 expect(f.root.querySelector('[aria-label="最大长度（0为不限）"]')).toBe(length);expect(length.value).toBe('4');expect(size.value).toBe('18');expect(document.activeElement).toBe(apply)
})
it('radio duplicate rejection preserves option and coordinates for correction',async()=>{
 const f=fixture('radio'),value=f.root.querySelector<HTMLInputElement>('[aria-label="新增选项值"]')!,x=f.root.querySelector<HTMLInputElement>('[aria-label="左下角 X"]')!
 value.value='Yes';x.value='123';const apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-radio-extension-apply]')!;apply.focus();apply.click();await Promise.resolve()
 expect(f.panel.element.textContent).toContain('重复');expect(f.draft.operations).toEqual([])
 expect(f.root.querySelector('[aria-label="新增选项值"]')).toBe(value);expect(value.value).toBe('Yes');expect(x.value).toBe('123');expect(document.activeElement).toBe(apply)
})
it('radio creation uses editable rows, exclusive selection and exact source-bound operations',async()=>{
 const f=fixture('create');(f.panel as ReturnType<typeof bindPdfFormCreatePanel>).open('radio')
 const table=f.root.querySelector<HTMLTableElement>('table[aria-label="单选选项"]')!;expect(table).not.toBeNull()
 expect(table.parentElement?.getAttribute('role')).toBe('region')
 expect(table.tBodies[0].rows).toHaveLength(2);expect(f.root.querySelector('textarea')).toBeNull()
 f.root.querySelector<HTMLInputElement>('[data-pdf-form-create-name]')!.value='new_consent'
 f.root.querySelector<HTMLButtonElement>('[data-pdf-radio-row-add]')!.click();expect(table.tBodies[0].rows).toHaveLength(3)
 const rows=table.tBodies[0].rows,third=rows[2]
 third.querySelector<HTMLInputElement>('[data-radio-value]')!.value='Maybe'
 third.querySelector<HTMLInputElement>('[data-radio-coordinate="0"]')!.value='130'
 third.querySelector<HTMLInputElement>('input[type="radio"]')!.click()
 expect(table.querySelectorAll('input[type="radio"]:checked')).toHaveLength(1)
 f.root.querySelector<HTMLButtonElement>('[data-pdf-form-create-apply]')!.click();await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 expect(f.draft.operations[0]).toMatchObject({kind:'createFormField',sourceSha256:sha,fieldKind:'radio',fieldName:'new_consent',pageId,rect:[10,50,30,70],radioWidgets:[{pageId,exportValue:'Yes',rect:[10,50,30,70],checked:false},{pageId,exportValue:'No',rect:[50,50,70,70],checked:false},{pageId,exportValue:'Maybe',rect:[130,50,150,70],checked:true}]})
})
it('radio rows retain two minimum, cap at 64 and return focus after row removal',()=>{
 const f=fixture('create');(f.panel as ReturnType<typeof bindPdfFormCreatePanel>).open('radio')
 const table=f.root.querySelector<HTMLTableElement>('table[aria-label="单选选项"]')!;expect(table).not.toBeNull()
 expect([...table.querySelectorAll('[data-radio-remove]')].every(button=>button.matches(':disabled'))).toBe(true)
 const add=f.root.querySelector<HTMLButtonElement>('[data-pdf-radio-row-add]')!;add.click()
 const remove=table.tBodies[0].rows[2].querySelector<HTMLButtonElement>('[data-radio-remove]')!;remove.focus();remove.click()
 expect(table.tBodies[0].rows).toHaveLength(2);expect(document.activeElement).toBe(add)
 for(let index=2;index<64;index++)add.click()
 expect(table.tBodies[0].rows).toHaveLength(64);expect(add.disabled).toBe(true);expect(f.draft.operations).toEqual([])
})
it('radio creation can explicitly start with no selected option',async()=>{
 const f=fixture('create');(f.panel as ReturnType<typeof bindPdfFormCreatePanel>).open('radio')
 f.root.querySelector<HTMLInputElement>('[data-pdf-form-create-name]')!.value='unselected_consent'
 const clear=f.root.querySelector<HTMLButtonElement>('[data-pdf-radio-selection-clear]')!;expect(clear).not.toBeNull();clear.click()
 expect(f.root.querySelectorAll('input[type=radio]:checked')).toHaveLength(0)
 f.root.querySelector<HTMLButtonElement>('[data-pdf-form-create-apply]')!.click();await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 expect((f.draft.operations[0].radioWidgets as {checked:boolean}[]).every(widget=>!widget.checked)).toBe(true)
})
it('adding after a middle-row removal generates a unique initial option value',()=>{
 const f=fixture('create');(f.panel as ReturnType<typeof bindPdfFormCreatePanel>).open('radio')
 const add=f.root.querySelector<HTMLButtonElement>('[data-pdf-radio-row-add]')!;add.click()
 const table=f.root.querySelector<HTMLTableElement>('table[aria-label="单选选项"]')!
 table.tBodies[0].rows[1].querySelector<HTMLButtonElement>('[data-radio-remove]')!.click();add.click()
 const values=[...table.querySelectorAll<HTMLInputElement>('[data-radio-value]')].map(input=>input.value)
 expect(values).toEqual(['Yes','Option3','Option4']);expect(new Set(values).size).toBe(values.length);expect(f.draft.operations).toEqual([])
})
for(const kind of ['text','radio'] as const)it(`${kind}: empty eligible target list disables all settings`,()=>{
 const f=fixture(kind);f.options.model=()=>({...model,formDesignWidgets:[]});f.panel.refresh()
 expect([...f.panel.element.querySelectorAll('input,select,textarea,fieldset button')].every(control=>control.matches(':disabled'))).toBe(true)
 expect(f.draft.operations).toEqual([])
})
