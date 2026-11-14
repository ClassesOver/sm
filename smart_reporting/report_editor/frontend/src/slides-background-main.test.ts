import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
const images=vi.hoisted(()=>({pick:vi.fn(),prepare:vi.fn(),canvas:vi.fn()}))
vi.mock('./slides-native-images',async original=>({...await original<typeof import('./slides-native-images')>(),pickSlideImage:images.pick,prepareSlideImage:images.prepare}))
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update:images.canvas,destroy(){}})}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});images.pick.mockReset();images.prepare.mockReset();images.canvas.mockReset()})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.unstubAllGlobals()})
async function fixture(){
 const source={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:5143500},slides:[0,1].map(slideIndex=>({slideIndex,elements:[],backgroundOwn:true,backgroundImage:{mode:'stretch'},backgroundImageSource:{sha256:'b'.repeat(64),size:64}}))}
 const tree={slides:source.slides.map(s=>({...s,widthPx:960,heightPx:540,scale:1,nodes:[],background:{kind:'image',mode:'stretch',dataUrl:'data:image/png;base64,fixture'},bgOwn:true}))}
 const draft=new NativeDraft({documentId:'background-test',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:tree)
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready;await vi.waitFor(()=>expect(images.canvas).toHaveBeenCalled())
 shell.editor.querySelector<HTMLButtonElement>('[data-command="formatBackground"]')!.click()
 return {draft,shell,request,view}
}
function button(shell:ReturnType<typeof createEditorShell>,text:string){return [...shell.editor.querySelectorAll<HTMLButtonElement>('.slides-background-pane-host button')].find(b=>b.textContent===text)!}
it('原图模式与全部复用不选文件，实际预览携带journal；Undo/Redo/恢复保留绑定',async()=>{
 const {draft,shell,request}=await fixture();button(shell,'平铺').click()
 await vi.waitFor(()=>expect(draft.operations[0]?.backgroundImageReuses).toEqual([{sourceSlideIndex:0,expectedSha256:'b'.repeat(64),expectedSize:64,slideIndices:[0],tile:true}]))
 button(shell,'应用到全部').click();expect(draft.operations[0]?.backgroundImageReuses).toEqual([{sourceSlideIndex:0,expectedSha256:'b'.repeat(64),expectedSize:64,slideIndices:[0,1],tile:true}]);expect(images.pick).not.toHaveBeenCalled()
 await vi.waitFor(()=>expect(request.mock.calls.some(call=>call[0]==='render-tree'&&JSON.stringify(call).includes('backgroundImageReuses'))).toBe(true))
 shell.editor.querySelector<HTMLButtonElement>('[aria-label="撤销"]')!.click();expect(draft.operations[0]?.backgroundImageReuses).toMatchObject([{slideIndices:[0]}])
 shell.editor.querySelector<HTMLButtonElement>('[aria-label="重做"]')!.click();expect(draft.operations[0]?.backgroundImageReuses).toMatchObject([{slideIndices:[0,1]}])
})
it('独立隐藏图形保留图片，不写入其他填充',async()=>{
 const {draft,shell}=await fixture();shell.editor.querySelector<HTMLInputElement>('.slides-background-pane-host input[type=checkbox]')!.click()
 expect(draft.operations[0]?.backgroundGraphics).toEqual([{slideIndex:0,hidden:true}]);expect(draft.operations[0]?.backgroundImageReuses).toBeUndefined();expect(images.pick).not.toHaveBeenCalled()
})
it.each(['slide','close','dispose','draft','save'])('迟到解码在%s变化后不得提交',async change=>{
 const {draft,shell,view}=await fixture();let finish!:(value:any)=>void
 images.pick.mockResolvedValue(new File(['x'],'背景.png'));images.prepare.mockReturnValue(new Promise(resolve=>{finish=resolve}))
 button(shell,'选择图片…').click();await vi.waitFor(()=>expect(images.prepare).toHaveBeenCalled())
 if(change==='slide')shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click()
 else if(change==='close')shell.editor.querySelector<HTMLButtonElement>('.slides-background-pane-host [aria-label="关闭格式窗格"]')!.click()
 else if(change==='dispose')view.dispose()
 else if(change==='save')draft.beginSave()
 else draft.setOperations([{kind:'editSlides',transitions:[{slideIndex:0,kind:'fade'}]}])
 const before=JSON.stringify(draft.operations);finish({bytesBase64:'fixture',extension:'png'});await new Promise(resolve=>setTimeout(resolve,20));expect(JSON.stringify(draft.operations)).toBe(before)
})

it('保存立即flush颜色，而切页丢弃未提交颜色',async()=>{
 const {draft,shell}=await fixture();button(shell,'渐变填充').click();shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click();await new Promise(resolve=>setTimeout(resolve,250));expect(draft.operations).toEqual([])
 button(shell,'渐变填充').click();shell.save.click();await vi.waitFor(()=>expect(draft.operations[0]?.backgroundGradients).toMatchObject([{slideIndices:[1]}]))
})
