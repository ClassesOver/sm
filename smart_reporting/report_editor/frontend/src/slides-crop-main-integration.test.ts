import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
import {openSlidesPictureCrop,type SlidesPictureCropOptions} from './slides-native-crop'
import {pickSlideImage} from './slides-native-images'
import type {SlidesCanvasState} from './slides-canvas'
import {defaultDrawSize,resolveDrawRect} from './vendor/genoffice-slides/draw-shape'
const canvasStates=vi.hoisted(()=>[] as SlidesCanvasState[])
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update:(state:SlidesCanvasState)=>canvasStates.push(state),destroy(){}})}))
vi.mock('./slides-native-crop',()=>({openSlidesPictureCrop:vi.fn(()=>({dispose:vi.fn()}))}))
vi.mock('./slides-native-images',()=>({pickSlideImage:vi.fn(),prepareSlideImage:vi.fn()}))
beforeEach(()=>vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }))
afterEach(()=>{document.body.replaceChildren();document.documentElement.lang='';vi.clearAllMocks();vi.unstubAllGlobals();canvasStates.length=0})
const geometry={x:100,y:100,width:400,height:200}
const cropped={srcRect:{l:.25,t:0,r:0,b:0},geometry:{x:200,y:100,width:300,height:200}}
const source={revision:1,sha256:'a'.repeat(64),size:{cx:12192000,cy:6858000},slides:[{slideIndex:0,elements:[
 {id:'picture',type:'picture',name:'来源图',text:'',editable:false,arrangeEditable:true,deletable:true,pictureCropEditable:true,pictureSha256:'b'.repeat(64),pictureSize:68,pictureReplaceable:true,srcRect:null,geometry,pictureTransform:{rot:0,flipH:false,flipV:false}},
 {id:'title',type:'text',name:'标题',text:'原文',editable:true,geometry:{x:10,y:10,width:100,height:40}},
]}]}
const tree={slides:[{slideIndex:0,widthPx:1280,heightPx:720,background:{type:'solid',color:'#ffffff'},nodes:[
 {id:'render-picture',sourceId:'picture',type:'picture',dataUrl:'data:image/png;base64,fixture',box:{x:100,y:100,w:400,h:200,rotationDeg:0,flipH:false,flipV:false}},
]}]}
function newDraft(){const values=new Map<string,string>();return new NativeDraft({documentId:'crop-main',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'company',userId:'user',threadId:'thread'}},{getItem:k=>values.get(k)??null,setItem:(k,v)=>{values.set(k,v)},removeItem:k=>{values.delete(k)}})}
async function open(draft:NativeDraft){
 document.documentElement.lang='zh-CN';document.body.innerHTML='<main id="app"></main>'
 const shell=createEditorShell(document.querySelector('#app')!,'full','pptx')
 const request=vi.fn(async(path:string,init?:RequestInit)=>{
  if(path==='deck')return source
  if(path!=='render-tree')return {revision:2,revisionRegistered:true,validation:{issues:[]}}
  const shapes=init?.method==='POST' ? JSON.parse(init.body as string).operations[0].shapes ?? [] : []
  const drawn=shapes.map((shape:{draftKey:string;geometry:typeof geometry},index:number)=>({
   id:`drawn-${index}`,sourceId:`engine-drawn-${index}`,type:'shape',
   box:{x:shape.geometry.x,y:shape.geometry.y,w:shape.geometry.width,h:shape.geometry.height,rotationDeg:0},
   draftKey:shape.draftKey,
  }))
  return {slides:[{...tree.slides[0],nodes:[...tree.slides[0]!.nodes,...drawn],
   draftShapeSources:drawn.map(({draftKey,sourceId}: {draftKey:string;sourceId:string})=>({draftKey,sourceId}))}]}
 })
 const previousCanvasCount=canvasStates.length
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx})
 await view.ready;await vi.waitFor(()=>expect(canvasStates.length).toBeGreaterThan(previousCanvasCount))
 const select=()=>{const control=shell.editor.querySelector<HTMLSelectElement>('#object-select')!;control.value='picture';control.dispatchEvent(new Event('change'))}
 select()
 const command=(name:string)=>shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
 const crop=()=>{expect(command('cropPicture').title).not.toContain('请选择');expect(command('cropPicture').disabled).toBe(false);command('cropPicture').click();return vi.mocked(openSlidesPictureCrop).mock.calls.at(-1)![1] as SlidesPictureCropOptions}
 return {shell,request,view,select,command,crop}
}
it('arms shape placement from the gallery and stages the drawn connector direction',async()=>{
 const draft=newDraft(),app=await open(draft)
 try{
  app.shell.editor.querySelector<HTMLButtonElement>('#slides-native-tab-insert')!.click()
  const pick=(kind:string)=>{
   app.command('insertShape').click()
   app.shell.editor.querySelector<HTMLButtonElement>(`.slides-shape-gallery:not([hidden]) [data-prst="${kind}"]`)!.click()
   return canvasStates.at(-1)!.shapeDrawing!
  }
  const line=pick('lineArrow')
  expect(draft.operations).toEqual([])
  expect(line.kind).toBe('lineArrow')
  line.commit(resolveDrawRect(line.kind,240,140,100,100,false))
  expect(draft.operations[0]?.shapes).toEqual([
   {slideIndex:0,kind:'lineArrow',geometry:{x:100,y:100,width:140,height:40},flipH:true,flipV:true,draftKey:expect.any(String)},
  ])
  const rectangle=pick('rect')
  rectangle.commit({x:16,y:32,...defaultDrawSize(rectangle.kind)})
  expect(draft.operations[0]?.shapes).toContainEqual({slideIndex:0,kind:'rect',geometry:{x:16,y:32,width:96,height:96},draftKey:expect.any(String)})
  const horizontal=pick('line')
  horizontal.commit({x:16,y:48,...defaultDrawSize(horizontal.kind)})
  expect(draft.operations[0]?.shapes).toContainEqual({slideIndex:0,kind:'line',geometry:{x:16,y:48,width:96,height:0},draftKey:expect.any(String)})
  await vi.waitFor(()=>expect(app.request.mock.calls.some(([path,init])=>path==='render-tree' && init?.method==='POST' &&
    JSON.parse(init.body as string).operations[0].shapes?.length===3)).toBe(true),{timeout:5000})
  const lastShape=(draft.operations[0]?.shapes as {draftKey:string}[]).at(-1)!
  const target=`draft-shape:${lastShape.draftKey}`
  await vi.waitFor(()=>expect(canvasStates.at(-1)!.selectedId).toBe(target),{timeout:5000})
  expect(canvasStates.at(-1)!.editableIds.has(target)).toBe(true)
  canvasStates.at(-1)!.onGeometry(target,{x:40,y:50,width:96,height:1})
  expect(draft.operations[0]?.edits ?? []).toEqual([])
  expect(draft.operations[0]?.shapes).toContainEqual({slideIndex:0,kind:'line',geometry:{x:40,y:50,width:96,height:0},draftKey:lastShape.draftKey})
  const cancelled=pick('ellipse')
  app.command('insertShape').focus()
  window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
  cancelled.commit({x:0,y:0,w:96,h:96})
  expect(draft.operations[0]?.shapes).toHaveLength(3)
  app.shell.save.click()
  await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const saved=JSON.parse(app.request.mock.calls.find(([path])=>path==='save')![1]!.body as string).operations[0]
  expect(saved.shapes).toHaveLength(3)
  expect(saved.shapes.at(-1)).toMatchObject({draftKey:lastShape.draftKey,geometry:{x:40,y:50,width:96,height:0}})
 }finally{app.view.dispose()}
})
it('shows crop in Picture Format Size and preserves pending picture orientation',async()=>{
 const draft=newDraft(),app=await open(draft)
 try{
  const button=app.command('cropPicture')
  expect(button.closest('[data-ribbon-group="Size"]')).not.toBeNull()
  expect(button.querySelector('img')).not.toBeNull()
  expect(button.getAttribute('aria-pressed')).toBe('false')
  app.command('rotatePictureRight').click()
  app.command('flipPictureH').click()
  const originalEdits=structuredClone(draft.operations[0]?.edits)
  expect(originalEdits).toEqual([
   {slideIndex:0,elementId:'picture',pictureTransform:{rot:5400000,flipH:true,flipV:false}},
  ])
  const unchanged=app.crop()
  expect(button.getAttribute('aria-pressed')).toBe('true')
  unchanged.onConfirm({srcRect:null,geometry})
  expect(button.getAttribute('aria-pressed')).toBe('false')
  expect(draft.operations[0]?.pictureCrops).toBeUndefined()
  app.crop().onConfirm(cropped)
  expect(draft.operations[0]?.edits).toEqual(originalEdits)
  expect(draft.operations[0]?.pictureCrops).toHaveLength(1)
  expect(button.getAttribute('aria-pressed')).toBe('false')
  app.crop().onCancel()
  expect(button.getAttribute('aria-pressed')).toBe('false')
 }finally{app.view.dispose()}
})
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
