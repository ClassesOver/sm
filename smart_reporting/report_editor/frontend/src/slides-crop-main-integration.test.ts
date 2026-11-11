import {afterEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
import {openSlidesPictureCrop,type SlidesPictureCropOptions} from './slides-native-crop'
import {pickSlideImage} from './slides-native-images'
import type {SlidesCanvasState} from './slides-canvas'
const canvasStates=vi.hoisted(()=>[] as SlidesCanvasState[])
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update:(state:SlidesCanvasState)=>canvasStates.push(state),destroy(){}})}))
vi.mock('./slides-native-crop',()=>({openSlidesPictureCrop:vi.fn(()=>({dispose:vi.fn()}))}))
vi.mock('./slides-native-images',()=>({pickSlideImage:vi.fn(),prepareSlideImage:vi.fn()}))
afterEach(()=>{document.body.replaceChildren();document.documentElement.lang='';vi.clearAllMocks();canvasStates.length=0})
const geometry={x:100,y:100,width:400,height:200}
const cropped={srcRect:{l:.25,t:0,r:0,b:0},geometry:{x:200,y:100,width:300,height:200}}
const source={revision:1,sha256:'a'.repeat(64),size:{cx:12192000,cy:6858000},slides:[{slideIndex:0,elements:[
 {id:'picture',type:'picture',name:'来源图',text:'',editable:false,arrangeEditable:true,deletable:true,pictureCropEditable:true,pictureSha256:'b'.repeat(64),pictureSize:68,pictureReplaceable:true,srcRect:null,geometry},
 {id:'title',type:'text',name:'标题',text:'原文',editable:true,geometry:{x:10,y:10,width:100,height:40}},
]}]}
const tree={slides:[{slideIndex:0,widthPx:1280,heightPx:720,background:{type:'solid',color:'#ffffff'},nodes:[
 {id:'render-picture',sourceId:'picture',type:'picture',dataUrl:'data:image/png;base64,fixture',box:{x:100,y:100,w:400,h:200,rotationDeg:0,flipH:false,flipV:false}},
]}]}
function newDraft(){const values=new Map<string,string>();return new NativeDraft({documentId:'crop-main',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'company',userId:'user',threadId:'thread'}},{getItem:k=>values.get(k)??null,setItem:(k,v)=>{values.set(k,v)},removeItem:k=>{values.delete(k)}})}
async function open(draft:NativeDraft){
 document.documentElement.lang='zh-CN';document.body.innerHTML='<main id="app"></main>'
 const shell=createEditorShell(document.querySelector('#app')!,'full','pptx')
 const request=vi.fn(async(path:string,_init?:RequestInit)=>path==='deck'?source:path==='render-tree'?tree:{revision:2,revisionRegistered:true,validation:{issues:[]}})
 const previousCanvasCount=canvasStates.length
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx})
 await view.ready;await vi.waitFor(()=>expect(canvasStates.length).toBeGreaterThan(previousCanvasCount))
 const select=()=>{const control=shell.editor.querySelector<HTMLSelectElement>('#object-select')!;control.value='picture';control.dispatchEvent(new Event('change'))}
 select()
 const command=(name:string)=>shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
 const crop=()=>{expect(command('cropPicture').title).not.toContain('请选择');expect(command('cropPicture').disabled).toBe(false);command('cropPicture').click();return vi.mocked(openSlidesPictureCrop).mock.calls.at(-1)![1] as SlidesPictureCropOptions}
 return {shell,request,view,select,command,crop}
}
it('裁切与frame一次撤销重做，刷新恢复并保持源SHA进入保存payload',async()=>{
 const draft=newDraft();let app=await open(draft)
 try{
  const options=app.crop()
  expect(options.box).toEqual(geometry);expect(options.slideWidthPx).toBe(1280)
  options.onConfirm(cropped)
  expect(draft.operations[0]?.pictureCrops).toEqual([{slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,...cropped}])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(draft.operations[0]?.pictureCrops).toHaveLength(1)
  app.view.dispose();app=await open(draft)
  expect(app.crop().box).toEqual(cropped.geometry)
  app.shell.save.click();await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const request=app.request.mock.calls.find(([path])=>path==='save')!
  const payload=JSON.parse(request[1]!.body as string)
  expect(payload.operations[0].pictureCrops[0]).toEqual({slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,...cropped})
 }finally{app.view.dispose()}
})
it('旧裁切回调拒绝覆盖撤销后的草稿，后续geometry优先投影与再次裁切',async()=>{
 const draft=newDraft(),app=await open(draft)
 try{
  app.crop().onConfirm(cropped)
  const stale=app.crop()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(()=>stale.onConfirm(cropped)).toThrow('变化')
  expect(draft.operations).toEqual([])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();app.select()
  const nextGeometry={x:250,y:150,width:300,height:200}
  canvasStates.at(-1)!.onGeometry('picture',nextGeometry)
  expect((draft.operations[0]?.edits as {geometry:object}[])[0]!.geometry).toEqual(nextGeometry)
  expect(app.crop().box).toEqual(nextGeometry)
 }finally{app.view.dispose()}
})
it('裁切与来源图替换双向互斥，删除撤回裁切且撤销恢复',async()=>{
 const draft=newDraft();let app=await open(draft)
 try{
  app.crop().onConfirm(cropped)
  expect(app.command('replacePicture').disabled).toBe(true)
  app.command('replacePicture').click();expect(pickSlideImage).not.toHaveBeenCalled()
  app.shell.editor.querySelector<HTMLButtonElement>('.object-delete')!.click()
  expect(draft.operations[0]?.pictureCrops).toBeUndefined()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations[0]?.pictureCrops).toHaveLength(1)
  app.view.dispose()
  const replacementDraft=newDraft()
  replacementDraft.setOperations([{kind:'editSlides',pictureReplacements:[{slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,extension:'png',bytesBase64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='}]}])
  vi.mocked(openSlidesPictureCrop).mockClear();app=await open(replacementDraft)
  expect(app.command('cropPicture').disabled).toBe(true)
  app.command('cropPicture').click();expect(openSlidesPictureCrop).not.toHaveBeenCalled()
 }finally{app.view.dispose()}
})
