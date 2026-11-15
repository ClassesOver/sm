import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
import type { createNativeApi, NativePreviewRequest } from './native-api'
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
const render=vi.hoisted(()=>vi.fn(async()=>['data:image/png;base64,QQ==','data:image/png;base64,Qg==']))
const downloadPdf = vi.hoisted(() => vi.fn())
vi.mock('./slides-print-render',()=>({renderSlidesPrintImages:render}))
vi.mock(import('./slides-export-download'), async original => ({
  ...await original(), downloadSlidesBlob: downloadPdf,
}))
const views:Array<ReturnType<typeof createSlidesEditorView>>=[]
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}});HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))};render.mockClear()})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
async function fixture(previewPdf?: (payload: NativePreviewRequest, signal: AbortSignal) => Promise<ArrayBuffer>,
                       saveAs?: ReturnType<typeof createNativeApi>['saveSlidesAs'],
                       openFile?: ReturnType<typeof createNativeApi>['openSlidesFile']){
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx'),sha='a'.repeat(64),draft=new NativeDraft({documentId:'print',revision:1,sourceSha256:sha,scope:{database:'f',companyId:'f',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 const slides=[{slideIndex:0,elements:[],notesText:'visible notes'},{slideIndex:1,elements:[],hidden:true,notesText:'hidden notes'}],tree={slides:slides.map(slide=>({...slide,widthPx:960,heightPx:540,nodes:[],background:{type:'solid',color:'#ffffff'}}))}
 const request=vi.fn(async(path:string,_init?:RequestInit)=>path==='deck'?{revision:1,sha256:sha,size:{cx:9144000,cy:5143500},slides}:path==='render-tree'?tree:path==='preview'?{sourceSha256:sha,model:{slides}}:Promise.reject(Error('unexpected '+path)))
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx,previewPdf,saveAs,openFile,filename:'季度.pptx'});views.push(view);await view.ready;request.mockClear();return {shell,sha,draft,request,view}
}
it('opens another local PPTX through the File shortcut and keeps the working draft', async () => {
 const openFile = vi.fn(async () => ({ documentId:'opened', revision:1, filename:'New deck.pptx',
   editor:{ openUrl:'/reports/v1/native/open/grant', url:'/reports/v1/native/open/grant', expiresAt:'' } }))
 const f = await fixture(undefined, undefined, openFile)
 const operations = [{kind:'editSlides', order:[1,0]}]
 f.draft.setOperations(operations)
 const button = f.shell.editor.querySelector<HTMLButtonElement>('[data-command="openFile"]')!
 const anchor = f.shell.editor.appendChild(document.createElement('button'))
 expect(button.dataset.sourceAction).toBe('onOpen')
 anchor.focus()
 const event = new KeyboardEvent('keydown', {key:'o',ctrlKey:true,bubbles:true,cancelable:true})
 anchor.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(true)
 const picker = f.shell.editor.querySelector<HTMLInputElement>('[aria-label="打开演示文稿"] input[type=file]')!
 const file = new File(['pptx fixture'], 'New deck.pptx')
 Object.defineProperty(picker, 'files', { value:[file] })
 picker.dispatchEvent(new Event('change'))
 await vi.waitFor(() => expect(f.shell.editor.querySelector('[aria-label="打开演示文稿"] a')?.getAttribute('href')).toContain('/reports/v1/native/open/grant'))
 expect(openFile).toHaveBeenCalledWith(file, expect.any(String), expect.any(AbortSignal))
 expect(f.draft.operations).toEqual(operations)
 expect(f.request).not.toHaveBeenCalled()
})
it('sends the current PPTX draft to Save As and opens a separate file without saving the source', async () => {
 const saveAs = vi.fn(async () => ({ documentId:'new', revision:1, filename:'副本.pptx',
   editor:{ openUrl:'/reports/v1/native/open/grant', url:'/reports/v1/native/open/grant', expiresAt:'' } }))
 const f = await fixture(undefined, saveAs)
 const operations = [{ kind:'editSlides', edits:[], order:[1, 0] }]
 f.draft.setOperations(operations)
 f.shell.editor.querySelector<HTMLButtonElement>('[data-command="saveAs"]')!.click()
 const form = f.shell.editor.querySelector<HTMLFormElement>('form:has([name="filename"])')!
 form.querySelector<HTMLInputElement>('input')!.value = '副本'
 form.dispatchEvent(new Event('submit', { bubbles:true, cancelable:true }))
 await vi.waitFor(() => expect(form.querySelector('a')?.getAttribute('href')).toContain('/reports/v1/native/open/grant'))
 expect(saveAs).toHaveBeenCalledWith({ filename:'副本.pptx', requestId:expect.any(String), expectedSha256:f.sha, operations })
 expect(f.request).not.toHaveBeenCalled()
 expect(f.draft.operations).toEqual(operations)
})
it('exports current PPTX draft through the PDF host without creating a revision', async () => {
 const previewPdf = vi.fn(async () => new TextEncoder().encode('%PDF-1.7\n').buffer)
 const f = await fixture(previewPdf)
 const input = f.shell.editor.appendChild(document.createElement('textarea'))
 const operations = [{ kind: 'editSlides', edits: [], order: [1, 0] }]
 input.addEventListener('blur', () => f.draft.setOperations(operations))
 input.focus()
 f.shell.editor.querySelector<HTMLButtonElement>('[data-command="exportPdf"]')!.click()
 await vi.waitFor(() => expect(downloadPdf).toHaveBeenCalledWith(expect.objectContaining({ type: 'application/pdf' }), '季度.pdf'))
 expect(previewPdf).toHaveBeenCalledWith({ expectedSha256: f.sha, operations }, expect.any(AbortSignal))
 expect(f.request).not.toHaveBeenCalled()
 expect(f.draft.operations).toEqual(operations)
})
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
