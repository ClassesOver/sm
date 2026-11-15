import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
import type {createNativeApi} from './native-api'

vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
beforeEach(()=>vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}}))
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.unstubAllGlobals()})
async function open(saveAs?: ReturnType<typeof createNativeApi>['saveSlidesAs']){
 const sha='a'.repeat(64),draft=new NativeDraft({documentId:'save-shortcut',revision:1,sourceSha256:sha,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const source={revision:1,sha256:sha,size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,notesText:'原备注',notesEditable:true,elements:[]}]}
 const request=vi.fn(async(path:string,_init?:RequestInit)=>path==='deck'?source:path==='render-tree'?{slides:[{slideIndex:0,widthPx:960,heightPx:540,nodes:[]}]}:{revision:2,revisionRegistered:true,validation:{issues:[]}})
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx,saveAs});views.push(view);await view.ready
 const input=shell.editor.querySelector<HTMLTextAreaElement>('[data-notes-text]')!;input.focus()
 const key=(extra:KeyboardEventInit={})=>{const event=new KeyboardEvent('keydown',{key:'s',ctrlKey:true,bubbles:true,cancelable:true,...extra});document.activeElement!.dispatchEvent(event);return event}
 const type=(value:string)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))}
 const saves=()=>request.mock.calls.filter(([path])=>path==='save')
 request.mockClear();return {shell,draft,sha,input,view,key,type,saves}
}
it.each(['ctrlKey','metaKey'] as const)('saves the current notes draft once with %s+S through the existing revision action',async modifier=>{
 const f=await open();f.type('未失焦的新备注')
 expect(f.key({ctrlKey:false,[modifier]:true}).defaultPrevented).toBe(true)
 await vi.waitFor(()=>expect(f.saves()).toHaveLength(1))
 const payload=JSON.parse(f.saves()[0]![1]!.body as string)
 expect(payload.expectedSha256).toBe(f.sha);expect(payload.operations[0].notesEdits).toEqual([{slideIndex:0,text:'未失焦的新备注'}])
 f.key({repeat:true});expect(f.saves()).toHaveLength(1)
})
it('commits a blur-bound editor value before invoking save',async()=>{
 const f=await open(),input=f.shell.editor.appendChild(document.createElement('input'))
 input.addEventListener('blur',()=>f.type('失焦提交'));input.focus()
 expect(f.key().defaultPrevented).toBe(true)
 await vi.waitFor(()=>expect(f.saves()).toHaveLength(1))
 expect(JSON.parse(f.saves()[0]![1]!.body as string).operations[0].notesEdits).toEqual([{slideIndex:0,text:'失焦提交'}])
})
it('keeps composition, modal input, external focus and modified shortcuts outside save routing',async()=>{
 const f=await open();f.type('保留草稿')
 for(const extra of [{altKey:true},{shiftKey:true},{isComposing:true},{keyCode:229}])expect(f.key(extra).defaultPrevented).toBe(false)
 const dialog=f.shell.editor.appendChild(document.createElement('dialog')),input=dialog.appendChild(document.createElement('input'));input.focus();expect(f.key().defaultPrevented).toBe(false)
 const outside=document.body.appendChild(document.createElement('input'));outside.focus();expect(f.key().defaultPrevented).toBe(false)
 expect(f.saves()).toEqual([])
})
it('does not save a composing notes draft and permits saving after composition ends',async()=>{
 const f=await open();f.input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));f.type('中文输入')
 f.key();expect(f.saves()).toEqual([])
 f.input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));f.key()
 await vi.waitFor(()=>expect(f.saves()).toHaveLength(1))
 expect(JSON.parse(f.saves()[0]![1]!.body as string).operations[0].notesEdits).toEqual([{slideIndex:0,text:'中文输入'}])
})
it('does not blur or save during repeats or locked saves and unregisters on disposal',async()=>{
 const f=await open();f.type('保留草稿');const blurred=vi.fn();f.input.addEventListener('blur',blurred)
 expect(f.key({repeat:true}).defaultPrevented).toBe(true);expect(blurred).not.toHaveBeenCalled();expect(f.saves()).toEqual([])
 f.shell.save.disabled=true;expect(f.key().defaultPrevented).toBe(true);expect(blurred).not.toHaveBeenCalled();expect(f.saves()).toEqual([])
 f.view.dispose();expect(f.key().defaultPrevented).toBe(false)
})

it.each(['ctrlKey', 'metaKey'] as const)('opens Save As with %s+Shift+S and only submits after confirmation', async modifier => {
  const saveAs = vi.fn(async () => { throw new Error('fixture stops after the request') })
  const f = await open(saveAs)
  f.type('Source notes before Save As')
  const command = f.shell.editor.querySelector<HTMLButtonElement>('[data-command="saveAs"]')!
  expect(command.getAttribute('aria-keyshortcuts')).toBe('Control+Shift+S Meta+Shift+S')
  const shortcut = { ctrlKey: false, [modifier]: true, shiftKey: true, key: 'S' }
  expect(f.key(shortcut).defaultPrevented).toBe(true)
  const filename = f.shell.editor.querySelector<HTMLInputElement>('input[name="filename"]')!
  expect(document.activeElement).toBe(filename)
  filename.value = 'My slides'
  expect(f.key({ ...shortcut, repeat: true }).defaultPrevented).toBe(false)
  expect(f.key(shortcut).defaultPrevented).toBe(false)
  expect(filename.value).toBe('My slides')
  expect(saveAs).not.toHaveBeenCalled()
  filename.form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await vi.waitFor(() => expect(saveAs).toHaveBeenCalledOnce())
  expect(saveAs).toHaveBeenCalledWith(expect.objectContaining({
    filename: 'My slides.pptx', expectedSha256: f.sha,
    operations: [expect.objectContaining({ notesEdits: [{ slideIndex: 0, text: 'Source notes before Save As' }] })],
  }))
  expect(f.saves()).toEqual([])
})
