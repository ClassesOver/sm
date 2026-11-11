import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesNativeRibbon } from './slides-native-ribbon'
import { slidesLayoutLabel } from './slides-native-ribbon-locales'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
import { createEditorShell } from './shell'

vi.mock('./slides-canvas', () => ({mountSlidesCanvas: () => ({update() {},destroy() {}})}))
afterEach(() => {document.body.replaceChildren();document.documentElement.lang='';vi.restoreAllMocks()})
const layouts = [
  {path:'builtin:blank',name:'Blank',layoutType:'blank',placeholders:[]},
  {path:'builtin:titleSlide',name:'Title Slide',layoutType:'title',placeholders:[]},
  {path:'ppt/slideLayouts/custom.xml',name:'Revenue Review',layoutType:'obj',placeholders:[]},
  {path:'ppt/slideLayouts/mismatch.xml',name:'Blank',layoutType:'cust',placeholders:[]},
]
it('preserves dynamic names, unknown enums and English mode while localizing exactly six pinned layout definitions', () => {
  const definitions=[
    ['titleSlide','Title Slide','title','标题幻灯片'],['titleContent','Title and Content','obj','标题和内容'],
    ['sectionHeader','Section Header','secHead','节标题'],['twoContent','Two Content','twoObj','两栏内容'],
    ['titleOnly','Title Only','titleOnly','仅标题'],['blank','Blank','blank','空白'],
  ] as const
  for(const [key,name,type,label] of definitions) {
    expect(slidesLayoutLabel({path:'builtin:'+key,name:name!,layoutType:type})).toBe(label)
    expect(slidesLayoutLabel({path:'ppt/source.xml',name:name!,layoutType:type})).toBe(label)
    expect(slidesLayoutLabel({path:'builtin:'+key,name:name!,layoutType:type},'en-US')).toBe(name)
  }
  expect(slidesLayoutLabel({path:'ppt/custom.xml',name:'Title Slide',layoutType:'blank'})).toBe('Title Slide · 空白')
  expect(slidesLayoutLabel({path:'ppt/custom.xml',name:'__proto__',layoutType:'obj'})).toBe('__proto__ · 标题和内容')
  expect(slidesLayoutLabel({path:'ppt/custom.xml',name:'Blank'})).toBe('Blank')
  expect(slidesLayoutLabel({path:'builtin:__proto__',name:''})).toBe('builtin:__proto__')
  expect(slidesLayoutLabel({path:'ppt/custom.xml',name:'客户标题',layoutType:'foreign'})).toBe('客户标题')
  expect(slidesLayoutLabel({path:'ppt/custom.xml',name:'空白',layoutType:'blank'})).toBe('空白')
})
it('localizes trusted standard layouts in initial and refreshed ribbon pickers without changing IDs or source names', () => {
  document.documentElement.lang='zh-CN'
  const host=document.createElement('div');document.body.append(host)
  const onAction=vi.fn(),ribbon=createSlidesNativeRibbon(host,{onAction,layouts})
  for(const picker of host.querySelectorAll<HTMLSelectElement>('select[data-command=layout],select[data-command=addSlideWithLayout]')) {
    expect([...picker.options].filter(option=>option.value).map(option=>[option.value,option.textContent])).toEqual([
      ['builtin:blank','空白'],['builtin:titleSlide','标题幻灯片'],['ppt/slideLayouts/custom.xml','Revenue Review · 标题和内容'],['ppt/slideLayouts/mismatch.xml','Blank'],
    ])
    expect(picker.getAttribute('aria-label')).toMatch(/版式/)
  }
  ribbon.setLayouts([{path:'ppt/slideLayouts/standard.xml',name:'Title and Content',layoutType:'obj'}, {path:'ppt/slideLayouts/custom.xml',name:'Quarterly Plan',layoutType:'titleOnly'}])
  const picker=host.querySelector<HTMLSelectElement>('select[data-command=addSlideWithLayout]')!
  expect([...picker.options].map(option=>option.textContent)).toEqual(['新建指定版式幻灯片…','标题和内容','Quarterly Plan · 仅标题'])
  picker.value='ppt/slideLayouts/custom.xml';picker.dispatchEvent(new Event('change'))
  expect(onAction).toHaveBeenCalledWith('addSlideWithLayout','ppt/slideLayouts/custom.xml')
  ribbon.dispose()
})
it('localizes inspector and pending new-slide labels while preserving custom object names and source operations', async () => {
  document.documentElement.lang='zh-CN'
  const container=document.createElement('div');document.body.append(container)
  const shell=createEditorShell(container,'full','pptx'),host=shell.editor
  const sha='a'.repeat(64),draft=new NativeDraft({documentId:'locale-review',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
  const deck={revision:1,sha256:sha,size:{cx:9144000,cy:5143500},layouts,slides:[{slideIndex:0,layoutPath:'builtin:blank',transitionApplyAllSafe:true,animations:[],elements:[{id:'source-textbox-id',type:'text',name:'TextBox 1',text:'源文字',editable:true,geometry:{x:10,y:10,width:100,height:30}}]}]}
  const nativeAI={start:vi.fn(),status:vi.fn(),accept:vi.fn(),cancel:vi.fn(),cancelRequest:vi.fn()}
  const view=createSlidesEditorView(host,{native:true,draft,nativeAI,save:shell.save,download:shell.exportPptx,request:async <T>(path:string)=> (path==='deck'?deck:{slides:[]}) as T})
  try {
    await view.ready
    const picker=host.querySelector<HTMLSelectElement>('#layout-select')!
    expect([...picker.options].map(option=>option.textContent)).toEqual(['空白','标题幻灯片','Revenue Review · 标题和内容','Blank'])
    expect(picker.getAttribute('aria-label')).toBe('当前页版式')
    expect(host.querySelector<HTMLSelectElement>('#object-select')!.selectedOptions[0]!.textContent).toBe('TextBox 1')
    expect(host.querySelector('.native-ai-context')!.textContent).toContain('TextBox 1')
    expect(host.querySelector('#object-select')!.getAttribute('aria-label')).toBe('可编辑对象')
    const create=host.querySelector<HTMLSelectElement>('select[data-command=addSlideWithLayout]')!
    create.value='builtin:blank';create.dispatchEvent(new Event('change'))
    expect(host.querySelector('.slide-list')!.textContent).toContain('新建幻灯片 · 空白')
    expect(draft.operations[0]!.newSlides).toEqual([{withLayout:'builtin:blank'}])
  } finally {view.dispose()}
})

it('synchronizes layout values immediately in both directions and keeps the original layout path in one draft', async () => {
  document.documentElement.lang='zh-CN'
  const container=document.createElement('div');document.body.append(container)
  const shell=createEditorShell(container,'full','pptx'),host=shell.editor
  const sha='a'.repeat(64),draft=new NativeDraft({documentId:'layout-sync',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
  const deck={revision:1,sha256:sha,size:{cx:9144000,cy:5143500},layouts,slides:[{slideIndex:0,layoutPath:'builtin:blank',transitionApplyAllSafe:true,animations:[],elements:[{id:'source-id',type:'text',name:'TextBox 1',text:'源文字',editable:true,geometry:{x:10,y:10,width:100,height:30}}]}]}
  const view=createSlidesEditorView(host,{native:true,draft,save:shell.save,download:shell.exportPptx,request:async <T>(path:string)=>(path==='deck'?deck:{slides:[]}) as T})
  try {
    await view.ready
    const inspector=host.querySelector<HTMLSelectElement>('#layout-select')!,ribbon=[...host.querySelectorAll<HTMLSelectElement>('select[data-command=layout]')]
    inspector.value='ppt/slideLayouts/custom.xml';inspector.dispatchEvent(new Event('change'))
    expect(draft.operations[0]!.slideLayouts).toEqual([{slideIndex:0,layoutPath:'ppt/slideLayouts/custom.xml'}])
    expect(ribbon.map(picker=>picker.value)).toEqual(ribbon.map(()=>'ppt/slideLayouts/custom.xml'))
    ribbon[0]!.value='builtin:titleSlide';ribbon[0]!.dispatchEvent(new Event('change'))
    expect(inspector.value).toBe('builtin:titleSlide')
    expect(ribbon.map(picker=>picker.value)).toEqual(ribbon.map(()=>'builtin:titleSlide'))
    expect(draft.operations[0]!.slideLayouts).toEqual([{slideIndex:0,layoutPath:'builtin:titleSlide'}])
    expect(draft.identity.sourceSha256).toBe(sha)
  } finally {view.dispose()}
})
