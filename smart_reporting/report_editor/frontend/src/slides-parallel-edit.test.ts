import { afterEach, expect, it, vi } from 'vitest'
import { act as reactAct } from 'react'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
afterEach(() => { document.body.innerHTML = ''; document.documentElement.lang = '' })
const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [
  { slideIndex: 0, elements: [{ id: 'title', type: 'text', name: '标题', text: '收入 收入', editable: true, arrangeEditable:true, geometry:{x:96,y:72,width:192,height:96}, findReplaceEditable: true },
    { id:'chart',type:'chart',name:'来源图表',text:'',editable:false,chartEditSafe:true,chartKind:'bar',chartCategories:['甲','乙'],chartSeries:[{name:'收入',values:[1,2]}],chartPointColors:[['#FF0000',null]],chartSeriesColors:['#4472C4'],chartStyle:{title:'',catAxisTitle:'',valAxisTitle:'',legendPos:'r',dataLabels:false,gridlines:true} },
    { id:'picture',type:'picture',name:'来源图片',text:'',editable:false,arrangeEditable:true,geometry:{x:96,y:288,width:192,height:96},pictureCropEditable:true,deletable:true,pictureReplaceable:true,pictureSha256:'b'.repeat(64),pictureSize:68 },
    { id:'format-shape',type:'shape',name:'格式形状',text:'',editable:true,brushSource:{supported:true,shape:{fill:'#123456',stroke:{color:'#345678',widthPt:2.25}}} },
    { id:'dashed-shape',type:'shape',name:'虚线形状',text:'',editable:true,brushSource:{supported:true,shape:{fill:'#123456'}} },
  ] },
  { slideIndex: 1, elements: [{ id: 'other', type: 'text', name: '正文', text: '收入', editable: true, findReplaceEditable: true }] },
] }
function newDraft() {
  const data = new Map<string, string>()
  return new NativeDraft({ documentId: 'parallel-pptx', revision: 1, sourceSha256: source.sha256,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } },
  { getItem: k => data.get(k) ?? null, setItem: (k, v) => { data.set(k, v) }, removeItem: k => { data.delete(k) } })
}
async function open(draft: NativeDraft, renderTree: unknown = { slides: [] }) {
  document.documentElement.lang = 'zh-CN'
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  const request = vi.fn(async (path: string) => path === 'deck' ? source : path === 'render-tree' ? renderTree
    : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as any, save: shell.save, download: shell.exportPptx })
  await view.ready
  return { shell, request, view }
}
it('形状侧栏与功能区共享来源值，保留线宽颜色、历史、刷新和保存，复杂轮廓不降级',async()=>{
 const draft=newDraft();let app=await open(draft)
 const act=(callback:()=>void)=>{const before=(globalThis as any).IS_REACT_ACT_ENVIRONMENT;(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;try{reactAct(callback)}finally{(globalThis as any).IS_REACT_ACT_ENVIRONMENT=before}}
 const choose=(id:string)=>{const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value=id;act(()=>select.dispatchEvent(new Event('change')))}
 const field=()=>app.shell.editor.querySelector<HTMLInputElement>('[data-shape-width]')!
 const pick=()=>{act(()=>app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-format-well="shape-fill"]')!.click());const input=document.querySelector<HTMLInputElement>('[data-chart-format-custom]')!;act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'#abcdef');input.dispatchEvent(new Event('input',{bubbles:true}))})}
 try {
  choose('format-shape');expect(field()).not.toBeNull();expect(field().value).toBe('2.25')
  vi.useFakeTimers();pick();act(()=>vi.advanceTimersByTime(200));const filled=draft.operations
  const outline=app.shell.editor.querySelector<HTMLInputElement>('[data-command="shapeOutline"]')!;outline.value='#112233';act(()=>outline.dispatchEvent(new Event('change')))
  expect(draft.operations[0]?.shapeStyles).toEqual([{slideIndex:0,elementId:'format-shape',fill:'#ABCDEF',stroke:{color:'#112233',widthPt:2.25}}])
  const colored=draft.operations
  act(()=>app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click());expect(draft.operations).toEqual(filled)
  act(()=>app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click());expect(draft.operations).toEqual(colored)
  choose('dashed-shape');const before=draft.operations
  const widthCommand=app.shell.editor.querySelector<HTMLSelectElement>('[data-command="shapeOutlineWidth"]')!;widthCommand.value='3';act(()=>widthCommand.dispatchEvent(new Event('change')))
  expect(draft.operations).toEqual(before);expect(field().disabled).toBe(true)
  choose('format-shape');pick();choose('dashed-shape');act(()=>vi.advanceTimersByTime(250));expect(draft.operations).toEqual(before)
  vi.useRealTimers();app.view.dispose();app=await open(draft);choose('format-shape');expect(field().value).toBe('2.25')
  act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field(),'4');field().dispatchEvent(new Event('input',{bubbles:true}));app.shell.save.click()})
  await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
  expect(JSON.parse(saved[1].body as string).operations[0].shapeStyles).toEqual([{slideIndex:0,elementId:'format-shape',fill:'#ABCDEF',stroke:{color:'#112233',widthPt:4}}])
 } finally{vi.useRealTimers();app.view.dispose()}
},15000)
it('原始图片基准接收迟到渲染数据，切换无历史，裁切与保存前flush保留来源身份',async()=>{
 class ImageSize { naturalWidth=48;naturalHeight=32;onload:(()=>void)|null=null;set src(_value:string){queueMicrotask(()=>this.onload?.())} }
 vi.stubGlobal('Image',ImageSize)
 const draft=newDraft()
 draft.setOperations([{kind:'editSlides',pictureCrops:[{slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:180,height:90}}]}])
 let resolveTree!:(value:unknown)=>void
 const tree=new Promise(resolve=>{resolveTree=resolve}),app=await open(draft,tree)
 const field=(axis:string)=>app.shell.editor.querySelector<HTMLInputElement>(`[data-geometry="${axis}"]`)!
 const checkbox=()=>app.shell.editor.querySelector<HTMLInputElement>('[data-geometry-original]')!
 try {
  const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value='picture';select.dispatchEvent(new Event('change'))
  const before=draft.operations
  resolveTree({slides:[{slideIndex:0,width:960,height:540,nodes:[{type:'picture',sourceId:'picture',dataUrl:'data:image/png;base64,fixture',box:{x:96,y:288,w:192,h:96,rotationDeg:0}}]}]})
  await vi.waitFor(()=>expect(checkbox().checked).toBe(true))
  expect(field('scaleWidth').value).toBe('375');expect(field('scaleHeight').value).toBe('281');expect(draft.operations).toEqual(before)
  checkbox().click();expect(field('scaleWidth').value).toBe('100');expect(draft.operations).toEqual(before)
  checkbox().click();field('scaleWidth').value='200';field('scaleWidth').dispatchEvent(new Event('change'))
  expect(draft.operations[0]?.pictureCrops).toMatchObject([{expectedSha256:'b'.repeat(64),expectedSize:68,srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:96,height:90}}])
  expect(draft.operations[0]?.edits).toBeUndefined()
  const changed=draft.operations
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations).toEqual(before)
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations).toEqual(changed)
  field('scaleHeight').value='150';app.shell.save.click()
  await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
  expect(JSON.parse(saved[1].body as string).operations[0].pictureCrops).toMatchObject([{geometry:{x:100,y:200,width:96,height:48},srcRect:{l:0.1,t:0,r:0,b:0}}])
 } finally {app.view.dispose();vi.unstubAllGlobals()}
},15000)
it('百分比缩放保留正文和裁切身份，历史回填保留基准，重选刷新重设且保存前flush',async()=>{
 const draft=newDraft();let app=await open(draft)
 const field=(axis:string)=>app.shell.editor.querySelector<HTMLInputElement>(`[data-geometry="${axis}"]`)!
 const choose=(id:string)=>{const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value=id;select.dispatchEvent(new Event('change'))}
 const change=(axis:string,value:string)=>{field(axis).value=value;field(axis).dispatchEvent(new Event('change'))}
 try {
  const text=app.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!;text.value='保留正文';text.dispatchEvent(new Event('input'))
  const before=draft.operations
  change('scaleWidth','150');expect(draft.operations[0]?.edits).toMatchObject([{text:'保留正文',geometry:{x:96,y:72,width:288,height:96}}])
  const scaled=draft.operations
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations).toEqual(before);expect(field('scaleWidth').value).toBe('100')
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations).toEqual(scaled);expect(field('scaleWidth').value).toBe('150')
  choose('picture');choose('title');expect(field('scaleWidth').value).toBe('100')
  change('scaleWidth','200');expect(draft.operations[0]?.edits).toMatchObject([{geometry:{width:576}}])
  app.view.dispose();app=await open(draft);expect(field('scaleWidth').value).toBe('100');expect(field('width').value).toBe('15.24')
 } finally {app.view.dispose()}
 const cropped=newDraft()
 cropped.setOperations([{kind:'editSlides',pictureCrops:[{slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:180,height:90}}]}])
 app=await open(cropped)
 try {
  choose('picture');change('scaleWidth','200')
  expect(cropped.operations[0]?.pictureCrops).toMatchObject([{expectedSha256:'b'.repeat(64),expectedSize:68,srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:360,height:90}}])
  expect(cropped.operations[0]?.edits).toBeUndefined()
  field('scaleHeight').value='150';app.shell.save.click()
  await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
  expect(JSON.parse(saved[1].body as string).operations[0].pictureCrops).toMatchObject([{srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:360,height:135}}])
 } finally {app.view.dispose()}
},15000)
it('厘米侧栏合并文字和裁切框，单笔历史、刷新、保存前flush及只读边界一致',async()=>{
 const draft=newDraft();let app=await open(draft)
 const field=(axis:string)=>app.shell.editor.querySelector<HTMLInputElement>(`[data-geometry="${axis}"]`)!
 const choose=(id:string)=>{const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value=id;select.dispatchEvent(new Event('change'))}
 const change=(axis:string,value:string)=>{field(axis).value=value;field(axis).dispatchEvent(new Event('change'))}
 try {
   expect(field('width')).not.toBeNull();expect(field('width').value).toBe('5.08')
   field('width').dispatchEvent(new Event('change'));expect(draft.operations).toEqual([])
   const text=app.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!;text.value='保留文字';text.dispatchEvent(new Event('input'))
   const before=draft.operations
   app.shell.editor.querySelector<HTMLInputElement>('[data-geometry-ratio]')!.click();change('width','10.16')
   expect(draft.operations[0]?.edits).toMatchObject([{text:'保留文字',geometry:{x:96,y:72,width:384,height:192}}])
   const resized=draft.operations
   app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations).toEqual(before)
   app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations).toEqual(resized)
   app.view.dispose();app=await open(draft);expect(field('width').value).toBe('10.16')
   choose('chart');expect(app.shell.editor.querySelector<HTMLElement>('.slides-geometry-pane')!.hidden).toBe(true)
   choose('picture');change('x','5.08');expect(draft.operations[0]?.edits).toMatchObject([{text:'保留文字'},{elementId:'picture',geometry:{x:192,y:288,width:192,height:96}}])
   field('y').value='5.08';field('y').dispatchEvent(new Event('input'))
   app.shell.save.click();await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
   const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
   expect(JSON.parse(saved[1].body as string).operations[0].edits).toMatchObject([{text:'保留文字'},{elementId:'picture',geometry:{x:192,y:192,width:192,height:96}}])
 } finally {app.view.dispose()}
 const cropped=newDraft()
 cropped.setOperations([{kind:'editSlides',pictureCrops:[{slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:180,height:90}}]}])
 app=await open(cropped)
 try {choose('picture');change('width','5.08');expect(cropped.operations[0]?.pictureCrops).toMatchObject([{srcRect:{l:0.1,t:0,r:0,b:0},geometry:{x:100,y:200,width:192,height:90}}]);expect(cropped.operations[0]?.edits).toBeUndefined()}
 finally {app.view.dispose()}
})
it('图表侧栏改色与交换、撤销、刷新一致，保存前提交防抖中的颜色',async()=>{
 const draft=newDraft();let app=await open(draft)
 const act=(callback:()=>void)=>{
   const environment=globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?:boolean },before=environment.IS_REACT_ACT_ENVIRONMENT
   environment.IS_REACT_ACT_ENVIRONMENT=true
   try { reactAct(callback) } finally { environment.IS_REACT_ACT_ENVIRONMENT=before }
 }
 const select=()=>app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 const choose=()=>{select().value='chart';select().dispatchEvent(new Event('change'))}
 const well=(point:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-chart-format-well="${point}"]`)!
 const pick=(point:string,color:string)=>{
   act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})))
   act(()=>well(point).click())
   const input=document.querySelector<HTMLInputElement>('[data-chart-format-custom]')!
   act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,color);input.dispatchEvent(new Event('input',{bubbles:true}))})
 }
 try {
   choose();expect(well('0:1')).not.toBeNull()
   vi.useFakeTimers()
   pick('0:1','#123abc');act(()=>vi.advanceTimersByTime(200))
   expect(draft.operations[0]?.chartEdits).toMatchObject([{pointColors:{0:{1:'#123ABC'}}}])
   app.shell.editor.querySelector<HTMLButtonElement>('[data-command="chartSwitchRowCol"]')!.click()
   const swapped=draft.operations
   expect(well('1:0').querySelector<HTMLElement>('.fp-color-well-swatch')!.style.background).toBe('rgb(18, 58, 188)')
   pick('0:0','#abcdef');pick('1:0','#112233');act(()=>vi.advanceTimersByTime(200))
   expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,pointColors:{0:{0:'#ABCDEF'},1:{0:'#112233'}}}])
   const colored=draft.operations
   app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations).toEqual(swapped)
   app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations).toEqual(colored)
   pick('0:0','#556677')
   select().value='title';select().dispatchEvent(new Event('change'));act(()=>vi.advanceTimersByTime(250))
   expect(draft.operations).toEqual(colored)
   expect(app.shell.editor.querySelector<HTMLElement>('.slides-chart-format-pane')!.hidden).toBe(true)
   choose();pick('1:0','#445566')
   act(()=>app.shell.save.click())
   vi.useRealTimers()
   await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
   const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
   expect(JSON.parse(saved[1].body as string).operations[0].chartEdits).toMatchObject([{pointColors:{0:{0:'#ABCDEF'},1:{0:'#445566'}}}])
   app.view.dispose();app=await open(draft);choose()
   expect(well('1:0').querySelector<HTMLElement>('.fp-color-well-swatch')!.style.background).toBe('rgb(68, 85, 102)')
 } finally { vi.useRealTimers();app.view.dispose() }
})
it('缩略图和配色卡片直接提交当前图表，历史、来源标记、刷新和保存一致',async()=>{
 const draft=newDraft();let app=await open(draft)
 const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 select.value='chart';select.dispatchEvent(new Event('change'))
 app.shell.editor.querySelector<HTMLButtonElement>('[data-command="chartSwitchRowCol"]')!.click()
 const swapped=draft.operations
 const bold=()=>app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-preset-card="bold"]')!
 expect(bold()).not.toBeNull();bold().click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,gapWidthPct:50,legendPos:'b',categories:['收入']}])
 expect(bold().getAttribute('aria-pressed')).toBe('true')
 const designed=draft.operations
 bold().click();expect(draft.operations).toEqual(designed)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!.click()
 document.querySelector<HTMLButtonElement>('[data-chart-scheme-card="warm"]')!.click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,colorScheme:'warm',gapWidthPct:50}])
 const colored=draft.operations
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(draft.operations).toEqual(designed)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(draft.operations).toEqual(swapped)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
 expect(draft.operations).toEqual(colored)
 app.view.dispose();app=await open(draft)
 const restored=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 restored.value='chart';restored.dispatchEvent(new Event('change'))
 expect(bold().getAttribute('aria-pressed')).toBe('true')
 app.shell.save.click()
 await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
 const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
 expect(JSON.parse(saved[1].body as string).operations[0].chartEdits).toMatchObject([{switchRowCol:true,colorScheme:'warm',gapWidthPct:50}])
 app.view.dispose()
})
it('单点配色跨交换行列保持坐标，合并多点与清除，刷新保存和历史保留',async()=>{
 const draft=newDraft();let app=await open(draft)
 const command=(name:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
 const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 select.value='chart';select.dispatchEvent(new Event('change'))
 expect(command('chartPointColors')).not.toBeNull()
 command('chartPointColors').click()
 const input=app.shell.editor.querySelector<HTMLInputElement>('[data-chart-point="0:1"]')!
 input.value='#123abc';input.dispatchEvent(new Event('input'))
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 command('chartSwitchRowCol').click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,pointColors:{1:{0:'#123ABC'}}}])
 command('chartPointColors').click()
 expect(app.shell.editor.querySelector<HTMLInputElement>('[data-chart-point="0:0"]')!.value).toBe('#ff0000')
 expect(app.shell.editor.querySelector<HTMLInputElement>('[data-chart-point="1:0"]')!.value).toBe('#123abc')
 const first=app.shell.editor.querySelector<HTMLInputElement>('[data-chart-point="0:0"]')!
 first.value='#abcdef';first.dispatchEvent(new Event('input'))
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{pointColors:{0:{0:'#ABCDEF'},1:{0:'#123ABC'}}}])
 const colored=draft.operations
 command('chartPointColors').click()
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-point-reset="1:0"]')!.click()
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{pointColors:{0:{0:'#ABCDEF'},1:{0:null}}}])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(draft.operations).toEqual(colored)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
 command('chartSwitchRowCol').click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{pointColors:{0:{0:'#ABCDEF',1:null}}}])
 app.view.dispose();app=await open(draft)
 app.shell.save.click()
 await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
 const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
 expect(JSON.parse(saved[1].body as string).operations[0].chartEdits).toMatchObject([{pointColors:{0:{0:'#ABCDEF',1:null}}}])
 app.view.dispose()
})
it('配色与命名样式合并交换草稿，撤销恢复、刷新和保存保留最终设计',async()=>{
 const draft=newDraft();let app=await open(draft)
 const command=(name:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
 const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 select.value='chart';select.dispatchEvent(new Event('change'))
 expect(command('chartDesignPresets')).not.toBeNull()
 command('chartSwitchRowCol').click()
 const before=draft.operations
 command('chartDesignPresets').click()
 app.shell.editor.querySelector<HTMLSelectElement>('[data-chart-palette]')!.value='warm'
 app.shell.editor.querySelector<HTMLSelectElement>('[data-chart-preset]')!.value='bold'
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,colorScheme:'warm',gapWidthPct:50,legendPos:'b',categories:['收入'],series:[{name:'甲',values:[1]},{name:'乙',values:[2]}]}])
 const designed=draft.operations
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(draft.operations).toEqual(before)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
 expect(draft.operations).toEqual(designed)
 app.view.dispose();app=await open(draft)
 app.shell.save.click()
 await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
 const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
 expect(JSON.parse(saved[1].body as string).operations[0].chartEdits).toMatchObject([{switchRowCol:true,colorScheme:'warm',gapWidthPct:50}])
 app.view.dispose()
})
it('交换行列使用当前草稿数据，后续编辑、撤销重做、恢复和保存维持同一方向',async()=>{
 const draft=newDraft();let app=await open(draft)
 const command=(name:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
 const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 select.value='chart';select.dispatchEvent(new Event('change'))
 expect(command('chartSwitchRowCol')).not.toBeNull()
 expect(command('chartSwitchRowCol').disabled).toBe(false)
 command('chartData').click()
 app.shell.editor.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!.value='84'
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 const before=draft.operations
 command('chartSwitchRowCol').click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,categories:['收入'],series:[{name:'甲',values:[84]},{name:'乙',values:[2]}]}])
 command('chartData').click()
 expect(app.shell.editor.querySelector<HTMLInputElement>('[data-chart-series="1"]')!.value).toBe('乙')
 app.shell.editor.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!.value='99'
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 const edited=draft.operations
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(draft.operations[0]?.chartEdits).toMatchObject([{switchRowCol:true,series:[{name:'甲',values:[84]},{name:'乙',values:[2]}]}])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(draft.operations).toEqual(before)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
 expect(draft.operations).toEqual(edited)
 app.view.dispose();app=await open(draft)
 app.shell.save.click()
 await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
 const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
 expect(JSON.parse(saved[1].body as string).operations[0].chartEdits).toMatchObject([{switchRowCol:true,categories:['收入'],series:[{name:'甲',values:[99]},{name:'乙',values:[2]}]}])
 app.view.dispose()
})

it('连续交换两次恢复原数据且不保留多余图表patch，过期数据弹窗不能覆盖交换',async()=>{
 const draft=newDraft(),app=await open(draft)
 const command=(name:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
 const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 select.value='chart';select.dispatchEvent(new Event('change'))
 expect(command('chartSwitchRowCol')).not.toBeNull()
 command('chartData').click()
 command('chartSwitchRowCol').click()
 const switched=draft.operations
 app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(draft.operations).toEqual(switched)
 expect(app.shell.editor.querySelector('dialog [role="alert"]')?.textContent).toContain('变化')
 app.shell.editor.querySelector('dialog')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
 command('chartSwitchRowCol').click()
 expect(draft.operations[0]?.chartEdits??[]).toEqual([])
 app.view.dispose()
})
it('查找不改草稿，全部替换只有一次历史且刷新恢复并进入保存请求', async () => {
  const draft = newDraft()
  let app = await open(draft)
  const command = (name: string) => app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
  expect(command('findReplace')).not.toBeNull()
  command('findReplace').click()
  const input = app.shell.editor.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!
  input.value = '收入'; input.dispatchEvent(new Event('input'))
  command('findNext').click()
  expect(draft.operations).toEqual([])
  app.shell.editor.querySelector<HTMLInputElement>('[aria-label="替换为"]')!.value = '营收'
  command('replaceAll').click()
  expect(draft.operations[0]?.edits).toEqual([
    { slideIndex: 0, elementId: 'title', text: '营收 营收' }, { slideIndex: 1, elementId: 'other', text: '营收' },
  ])
  command('closeFindReplace').click()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  app.view.dispose(); app = await open(draft)
  app.shell.save.click()
  await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const save = (app.request.mock.calls as unknown as [string, RequestInit][]).find(([path]) => path === 'save')!
  expect(JSON.parse(save[1].body as string).operations[0].edits).toHaveLength(2)
  app.view.dispose()
})

it('原生图片插入草稿可恢复、撤销并保留下载保存输入', async () => {
  const draft = newDraft(), image = { slideIndex: 0, bytesBase64: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9l8AAAAASUVORK5CYII=',
    extension: 'png', geometry: { x: 1, y: 2, width: 30, height: 20 } }
  draft.setOperations([{ kind: 'editSlides', images: [image] }])
  const app = await open(draft)
  expect(app.shell.editor.querySelector<HTMLButtonElement>('[data-command="insertPicture"]')!.disabled).toBe(false)
  app.shell.save.click()
  await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const call = (app.request.mock.calls as unknown as [string, RequestInit][]).find(([path]) => path === 'save')!
  expect(JSON.parse(call[1].body as string).operations[0].images).toEqual([image])
  app.view.dispose()
})

it('图表数据与类型合并，撤销一次只撤回类型，过期弹窗拒绝覆盖新草稿',async()=>{
  const draft=newDraft(),app=await open(draft)
  const command=(name:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
  const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  select.value='chart';select.dispatchEvent(new Event('change'))
  expect(command('chartData').disabled).toBe(false)
  command('chartData').click()
  app.shell.editor.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!.value='42'
  app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(draft.operations[0]?.chartEdits).toEqual([{slideIndex:0,elementId:'chart',categories:['甲','乙'],series:[{name:'收入',values:[42,2]}]}])
  command('chartType').click()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-kind="line"]')!.click()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(draft.operations[0]?.chartEdits).toHaveLength(1)
  expect(draft.operations[0]?.chartEdits).toMatchObject([{kind:'line',series:[{values:[42,2]}]}])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations[0]?.chartEdits).toMatchObject([{series:[{values:[42,2]}]}])
  expect((draft.operations[0]?.chartEdits as any)[0].kind).toBeUndefined()
  command('chartData').click()
  // An undo changes the live model while the dialog still holds its old values.
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  const before=draft.operations
  expect(before).toEqual([])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(draft.operations).toEqual(before)
  expect(app.shell.editor.querySelector('dialog [role="alert"]')?.textContent).toContain('变化')
  app.view.dispose()
})

it('图表元素格式与数据合并，撤销重做并刷新恢复后进入真实保存请求',async()=>{
  const draft=newDraft();let app=await open(draft)
  const command=(name:string)=>app.shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
  const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  select.value='chart';select.dispatchEvent(new Event('change'))
  expect(command('chartElements')).not.toBeNull()
  expect(command('chartElements').disabled).toBe(false)
  command('chartData').click()
  app.shell.editor.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!.value='84'
  app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  command('chartElements').click()
  app.shell.editor.querySelector<HTMLInputElement>('[data-chart-style="title"]')!.value='收入汇报'
  app.shell.editor.querySelector<HTMLSelectElement>('[data-chart-style="legendPos"]')!.value='none'
  app.shell.editor.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(draft.operations[0]?.chartEdits).toMatchObject([{title:'收入汇报',legendPos:'none',series:[{values:[84,2]}]}])
  command('chartElements').click()
  expect(app.shell.editor.querySelector<HTMLInputElement>('[data-chart-style="title"]')!.value).toBe('收入汇报')
  app.shell.editor.querySelector('dialog')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect((draft.operations[0]?.chartEdits as any)[0].title).toBeUndefined()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  app.view.dispose();app=await open(draft)
  expect(draft.operations[0]?.chartEdits).toMatchObject([{title:'收入汇报',series:[{values:[84,2]}]}])
  app.shell.save.click()
  await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
  const saved=(app.request.mock.calls as unknown as [string,RequestInit][]).find(([path])=>path==='save')!
  expect(JSON.parse(saved[1].body as string).operations[0].chartEdits).toMatchObject([{title:'收入汇报',legendPos:'none',series:[{values:[84,2]}]}])
  app.view.dispose()
})

it('删除来源图片时同时撤回替换，撤销后两者均恢复',async()=>{
  const draft=newDraft(),image={slideIndex:0,elementId:'picture',expectedSha256:'b'.repeat(64),expectedSize:68,
    bytesBase64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9l8AAAAASUVORK5CYII=',extension:'png'}
  draft.setOperations([{kind:'editSlides',pictureReplacements:[image]}])
  const app=await open(draft),select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  select.value='picture';select.dispatchEvent(new Event('change'))
  app.shell.editor.querySelector<HTMLButtonElement>('.object-delete')!.click()
  expect(draft.operations[0]?.pictureReplacements).toBeUndefined()
  expect(draft.operations[0]?.deletions).toEqual([{slideIndex:0,elementId:'picture'}])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations[0]?.pictureReplacements).toEqual([image])
  app.view.dispose()
})
