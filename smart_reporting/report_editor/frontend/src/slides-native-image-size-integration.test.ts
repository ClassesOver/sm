import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
import { imagePlacement, pickSlideImage, prepareSlideImage } from './slides-native-images'

vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
vi.mock('./slides-native-images',async importOriginal=>({
 ...await importOriginal<typeof import('./slides-native-images')>(),pickSlideImage:vi.fn(),prepareSlideImage:vi.fn(),
}))
afterEach(()=>{document.body.replaceChildren();document.documentElement.lang='';vi.clearAllMocks()})

it('修改页面尺寸后插图仍使用来源画布坐标，保存避免再次缩放目标坐标',async()=>{
 const source={revision:1,sha256:'a'.repeat(64),size:{cx:12192000,cy:6858000},slides:[
  {slideIndex:0,elements:[{id:'title',type:'text',name:'标题',text:'原文',editable:true}]},
 ]}
 const targetSize={cx:6096000,cy:3429000}
 const values=new Map<string,string>()
 const draft=new NativeDraft({documentId:'image-size-regression',revision:1,sourceSha256:source.sha256,
  scope:{database:'fixture',companyId:'company',userId:'user',threadId:'thread'}},
  {getItem:key=>values.get(key)??null,setItem:(key,value)=>{values.set(key,value)},removeItem:key=>{values.delete(key)}})
 draft.setOperations([{kind:'editSlides',slideSize:targetSize}])
 const file=new File(['fixture'],'原图.png',{type:'image/png'})
 const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
 vi.mocked(pickSlideImage).mockResolvedValue(file)
 vi.mocked(prepareSlideImage).mockImplementation(async(_file,size)=>({bytesBase64:png,extension:'png',descr:file.name,
  geometry:imagePlacement(size,{width:100,height:50})}))
 document.documentElement.lang='zh-CN'
 document.body.innerHTML='<main id="app"></main>'
 const shell=createEditorShell(document.querySelector('#app')!,'full','pptx')
 const request=vi.fn(async(path:string,_init?:RequestInit)=>path==='deck'?source:path==='render-tree'?{slides:[]}:
  {revision:2,revisionRegistered:true,validation:{issues:[]}})
 const view=createSlidesEditorView(shell.editor,{save:shell.save,download:shell.exportPptx,request:request as never,native:true,draft})
 try{
  await view.ready
  shell.editor.querySelector<HTMLButtonElement>('[data-command="insertPicture"]')!.click()
  await vi.waitFor(()=>expect(prepareSlideImage).toHaveBeenCalledWith(file,source.size))
  await vi.waitFor(()=>expect(draft.operations[0]?.images).toHaveLength(1))
  shell.save.click()
  await vi.waitFor(()=>expect(request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const save=request.mock.calls.find(([path])=>path==='save')!
  const payload=JSON.parse(save[1]!.body as string)
  expect(payload.operations[0].slideSize).toEqual(targetSize)
  expect(payload.operations[0].images[0].geometry).toEqual({x:590,y:335,width:100,height:50})
 }finally{view.dispose()}
})
