import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
const show=vi.hoisted(()=>vi.fn((_host:unknown,_options:unknown)=>({dispose(){}})));vi.mock('./slides-show',()=>({openSlidesShow:show}))
let view:ReturnType<typeof createSlidesEditorView>
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.open=true}})})
afterEach(()=>{view?.dispose();document.body.replaceChildren();vi.unstubAllGlobals()})
it('完整源对话框管理写NativeDraft历史，保留其它show，重排后放映真实顺序',async()=>{
 const source={sha256:'a'.repeat(64),revision:1,size:{cx:9144000,cy:5143500},customShowsEditable:true,customShows:[{id:'7',name:'重点',slideIndices:[2,0,2]},{id:'8',name:'保留',slideIndices:[1]}],slides:[0,1,2].map(slideIndex=>({slideIndex,elements:[]}))}
 const tree={slides:source.slides.map(s=>({...s,widthPx:960,heightPx:540,nodes:[],scale:1,background:{kind:'solid',color:'#fff'}}))}
 const draft=new NativeDraft({documentId:'custom-test',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}}),shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:path==='preview'?{sourceSha256:source.sha256,model:source}:tree)
 view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});await view.ready;await new Promise(r=>setTimeout(r,30))
 shell.editor.querySelector<HTMLButtonElement>('[data-command="customShows"]')!.click();document.querySelector<HTMLButtonElement>('[aria-label="下移"]')!.click();expect(draft.operations[0]?.customShows).toEqual([{id:'7',name:'重点',slideIndices:[0,2,2]},{id:'8',name:'保留',slideIndices:[1]}])
 document.querySelector<HTMLButtonElement>('dialog .modal-actions button')!.click()
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations[0]?.customShows).toBeUndefined()
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect((draft.operations[0]?.customShows as {slideIndices:number[]}[]|undefined)?.[0]?.slideIndices).toEqual([0,2,2])
 shell.editor.querySelector<HTMLButtonElement>('[data-command="customShows"]')!.click();shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(document.querySelector('dialog.slides-custom-shows-dialog')).toBeNull()
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();shell.editor.querySelector<HTMLButtonElement>('[data-command="customShows"]')!.click()
 const before=JSON.stringify(draft.operations);[...document.querySelectorAll<HTMLButtonElement>('dialog button')].find(b=>b.textContent==='放映此自定义放映')!.click();await vi.waitFor(()=>expect(show).toHaveBeenCalled());expect(show.mock.calls.at(-1)?.[1]).toMatchObject({customOrder:[0,2,2],startIndex:0});expect(JSON.stringify(draft.operations)).toBe(before)
 view.dispose()
})
