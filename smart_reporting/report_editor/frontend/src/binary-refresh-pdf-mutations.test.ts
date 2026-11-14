import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {startNativeEditor} from './native-main'
import type {NativeOperation} from './native-draft'
import {pdfReadingKey} from './pdf-reading-state'
import {saveViewState} from './genoffice-pdf-reading-state'
const actual=vi.hoisted(()=>({view:undefined as any,options:undefined as any,renderError:false}))
// 只观察实际 view 的返回值和 draft；不替换 PDF view/助手或构造假的 pending 状态。
vi.mock('./pdf-main',async()=>{
 const module=await vi.importActual<typeof import('./pdf-main')>('./pdf-main')
 return {...module,createPdfEditorView:async(...args:Parameters<typeof module.createPdfEditorView>)=>{actual.options=args[1];actual.view=await module.createPdfEditorView(...args);return actual.view}}
})
vi.mock('./source-validation',()=>({bytesSha256:async()=>'a'.repeat(64)}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
 const page={view:[0,0,300,400],rotate:0,userUnit:1,getViewport:({scale}:{scale:number})=>{if(actual.renderError)throw new Error('PDF renderer failed');return {width:300*scale,height:400*scale,viewBox:[0,0,300,400]}},getTextContent:async()=>({items:[]}),getAnnotations:async()=>[],render:()=>({promise:Promise.resolve(),cancel:vi.fn()})}
 const pdf={numPages:1,getPage:async()=>page,getMetadata:async()=>({info:{}}),getOutline:async()=>[],getAttachments:async()=>null,destroy:async()=>{}}
 return {AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{},getDocument:()=>({promise:Promise.resolve(pdf),destroy:async()=>{}})}
})
type Path='review'|'forms'|'attachment'
const paths:Path[]=['review','forms','attachment']
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0',fieldId='f'.repeat(64)
let fetcher:ReturnType<typeof vi.fn>,finishRequest:(value:Response)=>void,finishFile:(value:ArrayBuffer)=>void,failFile:(reason:Error)=>void,finishRefresh:(value:Response)=>void
let fileReads=0,refreshStatus='completed'
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status})
const task=()=>({taskId:'task',status:refreshStatus,result:{validationPassed:false,issueCodes:['code_only']},execution:{status:'completed',issueCodes:[]}})
const op=(path:Path):NativeOperation=>path==='review'?{kind:'rotatePage',pageId,delta:90}:path==='forms'?{kind:'setFormValue',fieldId,value:'late'}:{kind:'addAttachment',name:'report.txt',bytesBase64:'AQI='}
const button=(path:Path,name:string)=>document.querySelector<HTMLButtonElement>(`[data-pdf-${path==='review'?'review':'form-ai'}=${name}]`)!
const refreshButton=()=>document.querySelector<HTMLButtonElement>('[data-action=binary-refresh]')!
const calls=(part:string)=>fetcher.mock.calls.filter(([url])=>String(url).includes(part))
const mutationPending=()=>actual.view.mutationPending
beforeEach(()=>{
 document.body.innerHTML='<div id="app"></div>';localStorage.clear();actual.view=undefined;actual.options=undefined;actual.renderError=false;fileReads=0;refreshStatus='completed'
 vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}unobserve(){}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D)
 fetcher=vi.fn(async(url:string)=>{
  if(url.endsWith('/context'))return json({context:{documentId:'doc',revision:1,format:'pdf',origin:'report',sourceFile:{sha256:sha,size:2},scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},contextSha256:'b'.repeat(64),dataRefresh:{available:true},csrfToken:'token',editingEnabled:true,pdfReviewAIEnabled:true,pdfFormAIEnabled:true})
  if(url.endsWith('/file'))return new Response(new Uint8Array([1,2]))
  if(url.endsWith('/preview'))return json({sourceSha256:sha,model:{sourceSha256:sha,pages:[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},notesReadSafe:true}],formFields:[{fieldId,name:'Field',kind:'text',value:'',editable:true,expectedFieldSha256:'1'.repeat(64)}],attachments:[],attachmentsEditable:true}})
  if(url.endsWith('/ai/review/start'))return json({editId:'review',status:'succeeded',snapshotSha256:'c'.repeat(64),proposal:{operations:[op('review')],previewDigest:'d'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],answer:'审阅建议',notes:[],issues:[]}})
  if(url.endsWith('/ai/forms/start'))return json({editId:'forms',status:'succeeded',snapshotSha256:'c'.repeat(64),result:{answer:'填写建议',proposal:{summary:'填写',operations:[op('forms')],changes:[{fieldId,name:'Field',fieldKind:'text',before:'',after:'late'}],previewDigest:'d'.repeat(64),appliedOperationIndices:[0],skippedOperations:[]}}})
  if(url.endsWith('/accept'))return await new Promise<Response>(resolve=>{finishRequest=resolve})
  if(url.endsWith('/cancel'))return json({status:'cancelled'})
  if(url.endsWith('/recalculations'))return await new Promise<Response>(resolve=>{finishRefresh=resolve})
  if(url.includes('/by-request/'))return json(task())
  if(url.endsWith('/delivery'))return json({task:task(),delivery:{pdf:{downloadUrl:'/download/pdf'},word:{downloadUrl:'/wrong.docx'},validation:{ok:false,issues:[{code:'pdf_validation_failed',message:'PDF 后置验收失败'}]}}})
  return json({})
 })
 vi.stubGlobal('fetch',fetcher)
})
afterEach(()=>{window.dispatchEvent(new Event('pagehide'));actual.renderError=false;vi.restoreAllMocks();vi.unstubAllGlobals();document.body.replaceChildren()})
async function open(){history.replaceState({},'','/reports/v1/native/doc/1');await startNativeEditor();expect(actual.view).toBeDefined()}
async function candidate(path:Path){
 if(path==='attachment')return
 document.querySelector<HTMLButtonElement>(`[data-pdf-ai-mode=${path}]`)!.click()
 if(path==='forms'){
  const check=document.querySelector<HTMLInputElement>('[data-pdf-form-ai-field]')!;check.checked=true;check.dispatchEvent(new Event('change'))
  const input=document.querySelector<HTMLTextAreaElement>('[aria-label="AI 表单填写要求"]')!;input.value='填写字段';input.dispatchEvent(new Event('input'))
 }
 button(path,'start').click();await vi.waitFor(()=>expect(button(path,'accept').disabled).toBe(false))
}
function attach(){
 const file=new File([new Uint8Array([1,2])],'report.txt')
 Object.defineProperty(file,'arrayBuffer',{value:vi.fn(()=>{fileReads++;return new Promise<ArrayBuffer>((resolve,reject)=>{finishFile=resolve;failFile=reject})})})
 const input=document.querySelector<HTMLInputElement>('[aria-label="选择新增附件"]')!
 Object.defineProperty(input,'files',{configurable:true,value:[file]});input.dispatchEvent(new Event('change'))
}
async function begin(path:Path){if(path==='attachment')attach();else button(path,'accept').click();await vi.waitFor(()=>expect(path==='attachment'?fileReads:calls('/accept').length).toBe(1))}
function finish(path:Path,failed=false){if(path==='attachment'){if(failed)failFile(new Error('附件读取失败'));else finishFile(new Uint8Array([1,2]).buffer)}else finishRequest(failed?json({detail:{message:'采纳失败'}},409):json({operations:[op(path)]}))}
async function download(){
 await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
 const links=document.querySelectorAll<HTMLAnchorElement>('.binary-refresh-result a');expect(links).toHaveLength(1);expect(links[0].getAttribute('href')).toBe('/download/pdf')
 expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('PDF 后置验收失败');expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('pdf_validation_failed')
 expect(document.querySelector('.binary-refresh-result')!.textContent).not.toContain('文件验收通过')
}
async function refresh(){refreshButton().click();await vi.waitFor(()=>expect(calls('/recalculations').filter(([,init])=>init?.method==='POST')).toHaveLength(1));finishRefresh(json(task()));await download()}
it.each(paths)('%s exposes real PDF mutation state, blocks submit/flush and holds the lock through view.refresh',async path=>{
 await open();await candidate(path);await begin(path)
 expect(actual.options.draft.dirty).toBe(false);expect(refreshButton().disabled).toBe(true);expect(mutationPending()).toBe(true)
 expect(()=>actual.view.flushPendingEdits()).toThrow('当前 PDF 正在变更')
 await refreshButton().onclick!.call(refreshButton(),new MouseEvent('click') as PointerEvent)
 expect(calls('/recalculations')).toHaveLength(0)
 // 给真实阅读状态一个可见页框，使实际 refresh 等待两次动画帧。
 vi.spyOn(document.querySelector<HTMLElement>('.pdf-page')!,'getBoundingClientRect').mockReturnValue({x:0,y:0,top:0,left:0,bottom:400,right:300,height:400,width:300,toJSON(){}})
 const frames:FrameRequestCallback[]=[],raf=globalThis.requestAnimationFrame
 vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{frames.push(callback);return frames.length})
 finish(path);await vi.waitFor(()=>expect(actual.options.draft.operations).toEqual([op(path)]))
 await vi.waitFor(()=>expect(frames.length).toBeGreaterThan(0))
 expect(mutationPending()).toBe(true);expect(refreshButton().disabled).toBe(true)
 vi.stubGlobal('requestAnimationFrame',raf);for(const callback of frames.splice(0))callback(performance.now())
 await vi.waitFor(()=>expect(mutationPending()).toBe(false));expect(refreshButton().disabled).toBe(false)
})
it.each(['review','forms'] as const)('%s cancellation retains the in-flight lock and discards the tail before refresh can finish',async path=>{
 await open();await candidate(path);await begin(path);button(path,'cancel').click()
 expect(mutationPending()).toBe(true);expect(refreshButton().disabled).toBe(true)
 button(path,'start').click();expect(calls('/start')).toHaveLength(1)
 refreshButton().click();expect(calls('/recalculations')).toHaveLength(0)
 finish(path);await vi.waitFor(()=>expect(mutationPending()).toBe(false));expect(actual.options.draft.operations).toEqual([])
 refreshStatus='failed';await refresh();expect(actual.options.draft.operations).toEqual([])
})
it.each(paths)('%s failure releases the actual PDF/native lock and keeps failed-validation PDF delivery',async path=>{
 await open();await candidate(path);await begin(path);expect(mutationPending()).toBe(true)
 finish(path,true);await vi.waitFor(()=>expect(mutationPending()).toBe(false));expect(actual.options.draft.operations).toEqual([])
 expect(refreshButton().disabled).toBe(false);await refresh()
})
it.each(paths)('%s disposed pending work cannot write and releases only after the request/file tail',async path=>{
 await open();await candidate(path);await begin(path);window.dispatchEvent(new Event('pagehide'))
 expect(mutationPending()).toBe(true);finish(path);await vi.waitFor(()=>expect(mutationPending()).toBe(false))
 expect(actual.options.draft.operations).toEqual([])
})
it.each(paths)('%s cannot enter during refresh, then starts cleanly after failed refresh/download',async path=>{
 await open();await candidate(path);refreshButton().click();await vi.waitFor(()=>expect(calls('/recalculations')).toHaveLength(1))
 if(path==='attachment')attach();else {expect(button(path,'accept').disabled).toBe(true);button(path,'accept').onclick!.call(button(path,'accept'),new MouseEvent('click') as PointerEvent)}
 expect(calls('/accept')).toHaveLength(0);expect(fileReads).toBe(0);expect(actual.options.draft.operations).toEqual([])
 refreshStatus='failed';finishRefresh(json(task()));await download()
 await begin(path);finish(path);await vi.waitFor(()=>expect(actual.options.draft.operations).toEqual([op(path)]))
 await vi.waitFor(()=>expect(mutationPending()).toBe(false))
})
it.each(paths)('%s in flight prevents original-task recovery reads until failure releases the lock',async path=>{
 await open();await refresh();await candidate(path);await begin(path)
 const read=[...document.querySelectorAll<HTMLButtonElement>('.binary-refresh button')].find(b=>b.textContent==='读取原刷新任务')!
 const count=calls('/by-request/').length;expect(read.disabled).toBe(true)
 read.onclick!.call(read,new MouseEvent('click') as PointerEvent);await Promise.resolve();expect(calls('/by-request/')).toHaveLength(count)
 finish(path,true);await vi.waitFor(()=>expect(mutationPending()).toBe(false));expect(read.disabled).toBe(false)
 read.click();await vi.waitFor(()=>expect(calls('/by-request/').length).toBeGreaterThan(count));await download()
})

it.each(paths)('%s releases the pending boundary when actual PDF refresh fails after staging',async path=>{
 await open();await candidate(path);await begin(path);actual.renderError=true;finish(path)
 await vi.waitFor(()=>expect(actual.options.draft.operations).toEqual([op(path)]))
 await vi.waitFor(()=>expect(mutationPending()).toBe(false));expect(refreshButton().disabled).toBe(false)
 if(path!=='attachment')expect(document.querySelector(path==='review'?'.native-pdf-review':'.native-pdf-form-ai')!.textContent).toContain('预览刷新失败')
 else expect(document.body.textContent).toContain('PDF renderer failed')
 actual.renderError=false
})

it.each(paths)('%s respects cached recovery before the real view returns, and reports early pending mutations back to native',async path=>{
 await open();await refresh();const identity=actual.options.draft.identity
 window.dispatchEvent(new Event('pagehide'));document.body.innerHTML='<div id="app"></div>';actual.view=undefined
 saveViewState(pdfReadingKey(identity),{page:1,frac:0,scale:1,fitMode:null})
 const frames:FrameRequestCallback[]=[],raf=globalThis.requestAnimationFrame
 vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{frames.push(callback);return frames.length})
 const normal=fetcher.getMockImplementation()!;let finishRecovery!:(value:Response)=>void
 fetcher.mockImplementation(async(url:string)=>url.includes('/by-request/')?await new Promise<Response>(resolve=>{finishRecovery=resolve}):normal(url))
 const opening=startNativeEditor()
 await vi.waitFor(()=>expect(document.querySelector('[data-pdf-ai-mode=forms]')).not.toBeNull())
 await vi.waitFor(()=>expect(frames.length).toBeGreaterThan(0));expect(actual.view).toBeUndefined()
 const before=calls('/start').length
 if(path==='attachment')attach();else {
  if(path==='forms'){
   const check=document.querySelector<HTMLInputElement>('[data-pdf-form-ai-field]')
   // 打开实际助手渲染字段，再显式选择；刷新锁应保持入口保护。
   document.querySelector<HTMLButtonElement>('[data-pdf-ai-mode=forms]')!.click()
   const field=check??document.querySelector<HTMLInputElement>('[data-pdf-form-ai-field]')!;field.checked=true;field.dispatchEvent(new Event('change'))
   const input=document.querySelector<HTMLTextAreaElement>('[aria-label="AI 表单填写要求"]')!;input.value='填写字段';input.dispatchEvent(new Event('input'))
  }
  button(path,'start').onclick!.call(button(path,'start'),new MouseEvent('click') as PointerEvent)
 }
 await Promise.resolve();expect(calls('/start')).toHaveLength(before);expect(fileReads).toBe(0)
 finishRecovery(json(task()));await download();expect(actual.view).toBeUndefined()
 // 恢复已结束，但PDF初始真实刷新仍在等待动画帧；此时通知不能依赖返回后的handle。
 await candidate(path);await begin(path)
 const read=[...document.querySelectorAll<HTMLButtonElement>('.binary-refresh button')].find(b=>b.textContent==='读取原刷新任务')!
 expect(read.disabled).toBe(true)
 const reads=calls('/by-request/').length;read.onclick!.call(read,new MouseEvent('click') as PointerEvent);await Promise.resolve();expect(calls('/by-request/')).toHaveLength(reads)
 finish(path,true);await vi.waitFor(()=>expect(read.disabled).toBe(false))
 vi.stubGlobal('requestAnimationFrame',raf);for(const callback of frames.splice(0))callback(performance.now())
 await opening;expect(mutationPending()).toBe(false);expect(actual.options.draft.operations).toEqual([])
})

it('keeps the shared PDF boundary locked until all private mutation tails have drained',async()=>{
 await open();await candidate('review');await begin('review');await begin('attachment')
 expect(mutationPending()).toBe(true);expect(refreshButton().disabled).toBe(true)
 finish('review',true);await vi.waitFor(()=>expect(document.querySelector('.native-pdf-review')!.textContent).toContain('采纳失败'))
 expect(mutationPending()).toBe(true);expect(refreshButton().disabled).toBe(true)
 finish('attachment',true);await vi.waitFor(()=>expect(mutationPending()).toBe(false));expect(refreshButton().disabled).toBe(false)
 await refresh()
})
