import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
const media=vi.hoisted(()=>({pick:vi.fn(),prepare:vi.fn(),canvas:vi.fn()}))
vi.mock('./slides-media',async importOriginal=>({...await importOriginal<typeof import('./slides-media')>(),pickSlideMedia:media.pick,prepareSlideMedia:media.prepare}))
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update:media.canvas,destroy(){}})}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});media.pick.mockReset();media.prepare.mockReset();media.canvas.mockReset()})
afterEach(()=>{views.splice(0).forEach(v=>v.dispose());document.body.replaceChildren();vi.unstubAllGlobals()})
async function fixture(){
 const source={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:5143500},slides:[0,1].map(slideIndex=>({slideIndex,elements:[]}))}
 const tree={slides:source.slides.map(s=>({...s,widthPx:960,heightPx:540,nodes:[]}))}
 const draft=new NativeDraft({documentId:'media-test',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:tree)
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready
 return {source,draft,shell,request,view}
}
const asset={kind:'audio',extension:'wav',bytesBase64:btoa('RIFFfixture'),name:'样例.wav'}
it('音视频入口写单个原生草稿快照并送入实际预览，Undo/Redo恢复同一字节',async()=>{
 const {draft,shell,request}=await fixture();media.pick.mockResolvedValue(new File(['RIFFfixture'],'样例.wav'));media.prepare.mockResolvedValue(asset)
 const button=shell.editor.querySelector<HTMLButtonElement>('[data-command="insertAudio"]')!
 expect(button.disabled).toBe(false);button.click()
 await vi.waitFor(()=>expect(draft.operations[0]?.mediaInsertions).toEqual([{slideIndex:0,...asset}]))
 await vi.waitFor(()=>expect(request.mock.calls.some(call=>call[0]==='render-tree'&&JSON.stringify(call).includes('mediaInsertions'))).toBe(true))
 shell.editor.querySelector<HTMLButtonElement>('[aria-label="撤销"]')!.click();expect(draft.operations[0]?.mediaInsertions).toBeUndefined()
 shell.editor.querySelector<HTMLButtonElement>('[aria-label="重做"]')!.click();expect(draft.operations[0]?.mediaInsertions).toEqual([{slideIndex:0,...asset}])
})
it('文件选择取消不改草稿，不触发读取',async()=>{
 const {draft,shell}=await fixture();media.pick.mockResolvedValue(null)
 shell.editor.querySelector<HTMLButtonElement>('[data-command="insertVideo"]')!.click()
 await vi.waitFor(()=>expect(media.pick).toHaveBeenCalled());expect(draft.operations).toEqual([]);expect(media.prepare).not.toHaveBeenCalled()
})
it.each(['slide','dispose','draft','save'])('迟到读取在%s变化后不得提交',async change=>{
 const {draft,shell,view}=await fixture();let finish!:(value:typeof asset)=>void
 media.pick.mockResolvedValue(new File(['x'],'样例.wav'));media.prepare.mockReturnValue(new Promise(resolve=>{finish=resolve}))
 shell.editor.querySelector<HTMLButtonElement>('[data-command="insertAudio"]')!.click();await vi.waitFor(()=>expect(media.prepare).toHaveBeenCalled())
 if(change==='slide')shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click()
 else if(change==='dispose')view.dispose()
 else if(change==='save')draft.beginSave()
 else draft.setOperations([{kind:'editSlides',transitions:[{slideIndex:0,kind:'fade'}]}])
 const before=JSON.stringify(draft.operations);finish(asset);await new Promise(resolve=>setTimeout(resolve,20));expect(JSON.stringify(draft.operations)).toBe(before)
})

const recording=vi.hoisted(()=>({start:vi.fn()}))
vi.mock('./slides-screen-recording',()=>({startSlideScreenRecording:recording.start}))
it('录制停止结果复用媒体单快照，Undo不改变录制字节',async()=>{
 const {draft,shell}=await fixture();let finish!:(value:unknown)=>void
 const stop=vi.fn(),cancel=vi.fn()
 recording.start.mockImplementation(async(signal:AbortSignal)=>{signal.addEventListener('abort',cancel);return {stop,cancel,result:new Promise(resolve=>finish=resolve)}})
 const asset={kind:'video',extension:'webm',bytesBase64:btoa('recorded-webm'),name:'录制.webm'}
 media.prepare.mockResolvedValue(asset)
 const button=shell.editor.querySelector<HTMLButtonElement>('[data-command="screenRecording"]')!
 expect(button.disabled).toBe(false);button.click();await vi.waitFor(()=>expect(button.textContent).toContain('停止录制'))
 button.click();expect(stop).toHaveBeenCalledOnce()
 // 校验器要求有真实 PNG 头；完整 PNG 解码与 hash 在服务端独立核验。
 const png=new Uint8Array(24);png.set([137,80,78,71,13,10,26,10]);new DataView(png.buffer).setUint32(16,8);new DataView(png.buffer).setUint32(20,4)
 const poster={bytesBase64:btoa(String.fromCharCode(...png)),sha256:'a'.repeat(64)}
 finish({file:new File(['recorded-webm'],'录制.webm'),poster})
 await vi.waitFor(()=>expect(draft.operations[0]?.mediaInsertions).toEqual([{slideIndex:0,...asset,poster}]))
 shell.editor.querySelector<HTMLButtonElement>('[aria-label="撤销"]')!.click();expect(draft.operations[0]?.mediaInsertions).toBeUndefined()
})

it('Esc取消录制丢弃结果并释放会话，不产生媒体草稿',async()=>{
 const {draft,shell}=await fixture();let cancel=vi.fn()
 recording.start.mockImplementation(async(signal:AbortSignal)=>({stop:vi.fn(),cancel,result:new Promise((_,reject)=>signal.addEventListener('abort',()=>{cancel();reject(Error('取消'))}))}))
 const button=shell.editor.querySelector<HTMLButtonElement>('[data-command="screenRecording"]')!
 button.click();await vi.waitFor(()=>expect(button.textContent).toContain('停止录制'))
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
 await vi.waitFor(()=>expect(button.textContent).toContain('屏幕录制'));expect(cancel).toHaveBeenCalledOnce();expect(draft.operations).toEqual([])
})
