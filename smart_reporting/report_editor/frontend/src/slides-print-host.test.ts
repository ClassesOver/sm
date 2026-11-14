import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
const render=vi.hoisted(()=>vi.fn(async()=>['data:image/png;base64,QQ==','data:image/png;base64,Qg==']))
vi.mock('./slides-print-render',()=>({renderSlidesPrintImages:render}))
const views:Array<ReturnType<typeof createSlidesEditorView>>=[]
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}});HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))};render.mockClear()})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
async function fixture(){
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx'),sha='a'.repeat(64),draft=new NativeDraft({documentId:'print',revision:1,sourceSha256:sha,scope:{database:'f',companyId:'f',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 const slides=[{slideIndex:0,elements:[],notesText:'visible notes'},{slideIndex:1,elements:[],hidden:true,notesText:'hidden notes'}],tree={slides:slides.map(slide=>({...slide,widthPx:960,heightPx:540,nodes:[],background:{type:'solid',color:'#ffffff'}}))}
 const request=vi.fn(async(path:string,_init?:RequestInit)=>path==='deck'?{revision:1,sha256:sha,size:{cx:9144000,cy:5143500},slides}:path==='render-tree'?tree:path==='preview'?{sourceSha256:sha,model:{slides}}:Promise.reject(Error('unexpected '+path)))
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready;request.mockClear();return {shell,sha,draft,request,view}
}
it('loads the identity-bound current draft for printing without save/export or draft mutation',async()=>{
 const f=await fixture(),button=f.shell.editor.querySelector<HTMLButtonElement>('[data-command=print]')!;expect(button.disabled).toBe(false);button.click()
 await vi.waitFor(()=>expect(f.shell.editor.querySelector('.slides-print-dialog iframe')?.getAttribute('srcdoc')).toContain('QQ=='))
 const calls=f.request.mock.calls;expect(calls.map(([path])=>path)).toEqual(expect.arrayContaining(['render-tree','preview']));expect(calls).toHaveLength(2)
 for(const [,init]of calls)expect(JSON.parse(init!.body as string)).toEqual({expectedSha256:f.sha,operations:[]})
 expect(render).toHaveBeenCalledOnce();expect(f.draft.operations).toEqual([]);const preview=f.shell.editor.querySelector<HTMLIFrameElement>('.slides-print-dialog iframe')!;expect(preview.srcdoc).not.toContain('Qg==')
 f.view.dispose();expect(document.querySelector('.slides-print-dialog')).toBeNull()
})
it.each(['ctrlKey','metaKey'] as const)('opens the draft print preview with %s+P and releases the shortcut on disposal',async modifier=>{
 const f=await fixture(),button=f.shell.editor.querySelector<HTMLButtonElement>('[data-command=print]')!;button.focus()
 const event=new KeyboardEvent('keydown',{key:'p',[modifier]:true,bubbles:true,cancelable:true});button.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(true)
 await vi.waitFor(()=>expect(f.shell.editor.querySelector('.slides-print-dialog iframe')?.getAttribute('srcdoc')).toContain('QQ=='))
 expect(f.draft.operations).toEqual([]);f.view.dispose()
 const after=new KeyboardEvent('keydown',{key:'p',[modifier]:true,bubbles:true,cancelable:true});button.dispatchEvent(after);expect(after.defaultPrevented).toBe(false)
})
it('leaves other editor focus, modified shortcuts, composition and modal input alone',async()=>{
 const f=await fixture(),outside=document.body.appendChild(document.createElement('button')),button=f.shell.editor.querySelector<HTMLButtonElement>('[data-command=print]')!
 outside.focus();const external=new KeyboardEvent('keydown',{key:'p',ctrlKey:true,bubbles:true,cancelable:true});outside.dispatchEvent(external);expect(external.defaultPrevented).toBe(false)
 button.focus();for(const extra of [{altKey:true},{shiftKey:true},{isComposing:true}]){const event=new KeyboardEvent('keydown',{key:'p',ctrlKey:true,bubbles:true,cancelable:true,...extra});button.dispatchEvent(event);expect(event.defaultPrevented).toBe(false)}
 const dialog=f.shell.editor.appendChild(document.createElement('dialog')),input=dialog.appendChild(document.createElement('input'));dialog.showModal();input.focus();const modal=new KeyboardEvent('keydown',{key:'p',ctrlKey:true,bubbles:true,cancelable:true});input.dispatchEvent(modal);expect(modal.defaultPrevented).toBe(false)
 expect(f.request).not.toHaveBeenCalled();expect(f.shell.editor.querySelector('.slides-print-dialog')).toBeNull()
})
it('flushes the active editor input before freezing the keyboard print snapshot',async()=>{
 const f=await fixture(),input=f.shell.editor.appendChild(document.createElement('textarea')),operations=[{kind:'editSlides',edits:[],order:[1,0]}]
 input.addEventListener('blur',()=>f.draft.setOperations(operations));input.focus()
 input.dispatchEvent(new KeyboardEvent('keydown',{key:'p',ctrlKey:true,bubbles:true,cancelable:true}))
 await vi.waitFor(()=>expect(f.shell.editor.querySelector('.slides-print-dialog iframe')?.getAttribute('srcdoc')).toContain('QQ=='))
 expect(f.draft.operations).toEqual(operations)
 for(const [,init]of f.request.mock.calls)expect(JSON.parse(init!.body as string)).toEqual({expectedSha256:f.sha,operations})
 f.view.dispose();expect(document.activeElement).toBe(input)
})
