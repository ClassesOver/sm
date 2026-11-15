import { afterEach, expect, it, vi } from 'vitest'
import { bindNativeWordAssistant } from './native-word-assistant'
import { NativeDraft } from './native-draft'
afterEach(() => { document.body.replaceChildren(); localStorage.clear() })
function fixture(api: object) {
 const root=document.body.appendChild(document.createElement('div'))
 const draft=new NativeDraft({documentId:'word',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 let selected=[{blockId:'b1'}];const flush=vi.fn()
 const binding=bindNativeWordAssistant(root,{api:api as never,draft,selection:()=>selected,flushPendingEdits:flush})
 return {root,draft,binding,flush,setSelection:(value:typeof selected)=>{selected=value}}
}
const result={answer:'<img src=x>文档总结\n\n- **要点**',readingVersion:'draft',coverage:{scope:'document',totalBlocks:3,fullyReadBlockIds:['b1'],scopeReadComplete:false},citations:[{blockId:'opaque-block-hash',cellId:'opaque-cell-hash',blockNumber:1}],issues:[{code:'incomplete',message:'尚未完整读取'}],toolEvents:[{tool:'read_blocks'}]}
it('默认整篇、同步未保存编辑并只读展示真实覆盖',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'completed',result}),wordAICancel:vi.fn()}
 const {root,draft,binding,flush}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('文档总结'))
 expect(root.querySelector('.native-ai-answer li strong')?.textContent).toBe('要点')
 expect(flush).toHaveBeenCalled();expect(api.wordAIStart.mock.calls[0][0]).toMatchObject({action:'summarize',selection:[],operations:[]})
 expect(root.textContent).toContain('未保存草稿');expect(root.textContent).toContain('尚未完整读取');expect(root.textContent).toContain('1 / 3');expect(root.textContent).toContain('第 1 个内容块')
 expect(root.textContent).not.toContain('opaque-block-hash');expect(root.textContent).not.toContain('opaque-cell-hash');expect(root.textContent).toContain('（已选单元格）');expect(root.textContent).toContain('已执行工具：读取文档内容块');expect(root.querySelector('img')).toBeNull();expect(root.querySelector('svg')).not.toBeNull();expect(draft.operations).toEqual([]);expect(draft.dirty).toBe(false);binding.dispose()
})
it('GenOffice 常用摘要覆盖上次选区和输入，按整篇启动一次只读任务',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'completed',result}),wordAICancel:vi.fn()}
 const {root,draft,binding}=fixture(api)
 binding.open()
 root.querySelector<HTMLSelectElement>('[data-word-ai=scope]')!.value='selection'
 root.querySelector('textarea')!.value='上次的问题'
 binding.openDocumentSummary('总结这篇文档的主要内容和要点')
 binding.openDocumentSummary('第二次点击')
 await vi.waitFor(()=>expect(root.textContent).toContain('文档总结'))
 expect(api.wordAIStart).toHaveBeenCalledOnce()
 expect(api.wordAIStart.mock.calls[0][0]).toMatchObject({action:'summarize',instruction:'总结这篇文档的主要内容和要点',selection:[],operations:[]})
 expect(draft.dirty).toBe(false)
 binding.dispose()
})
it('显式选区提交且选择变化丢弃迟到回答',async()=>{
 let finish!:(value:object)=>void
 const api={wordAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),wordAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding,setSelection}=fixture(api);binding.open()
 const scope=root.querySelector<HTMLSelectElement>('[data-word-ai=scope]')!;scope.value='selection';scope.dispatchEvent(new Event('change'))
 root.querySelector<HTMLButtonElement>('[data-word-ai=summarize]')!.click()
 expect(api.wordAIStart.mock.calls[0][0].selection).toEqual([{blockId:'b1'}])
 setSelection([{blockId:'b2'}]);finish({taskId:'t',status:'completed',result})
 await vi.waitFor(()=>expect(root.textContent).toContain('草稿或选区已变化'));expect(root.textContent).not.toContain('文档总结');binding.dispose()
})
it('收起期间保留任务，重开后显示结果并保留输入草稿',async()=>{
 let finish!:(value:object)=>void
 const api={wordAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),wordAICancel:vi.fn()}
 const {root,binding}=fixture(api)
 binding.open('keyPoints')
 const panel=root.querySelector<HTMLElement>('.native-word-assistant')!
 const input=root.querySelector('textarea')!
 input.value='未发送的输入'
 root.querySelector<HTMLButtonElement>('[data-word-ai=close]')!.click()
 expect(panel.hidden).toBe(true)
 expect(api.wordAICancel).not.toHaveBeenCalled()
 binding.open()
 expect(panel.hidden).toBe(false)
 expect(input.value).toBe('未发送的输入')
 expect(api.wordAIStart).toHaveBeenCalledOnce()
 finish({taskId:'t',status:'completed',result})
 await vi.waitFor(()=>expect(root.textContent).toContain('文档总结'))
 expect(api.wordAICancel).not.toHaveBeenCalled()
 binding.dispose()
})
it('空选区不回退全文，问答必须输入',()=>{
 const api={wordAIStart:vi.fn(),wordAICancel:vi.fn()};const {root,binding,setSelection}=fixture(api);binding.open()
 expect(root.querySelector<HTMLButtonElement>('[data-word-ai=start]')!.disabled).toBe(true)
 setSelection([]);const scope=root.querySelector<HTMLSelectElement>('[data-word-ai=scope]')!;scope.value='selection';scope.dispatchEvent(new Event('change'))
 root.querySelector<HTMLButtonElement>('[data-word-ai=summarize]')!.click();expect(api.wordAIStart).not.toHaveBeenCalled();expect(root.textContent).toContain('选区无法可靠对应来源');binding.dispose()
})
it('读取同步后的草稿，运行期间变化不会展示旧回答',async()=>{
 let finish!:(value:object)=>void
 const api={wordAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),wordAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding,draft,flush}=fixture(api)
 flush.mockImplementationOnce(()=>draft.setOperations([{kind:'replaceText',blockId:'b1',text:'当前输入'}]))
 binding.open('summarize');expect(api.wordAIStart.mock.calls[0][0].operations).toEqual(draft.operations)
 draft.setOperations([{kind:'replaceText',blockId:'b1',text:'又修改'}]);finish({taskId:'t',status:'completed',result})
 await vi.waitFor(()=>expect(root.textContent).toContain('草稿或选区已变化'));expect(root.textContent).not.toContain('文档总结');binding.dispose()
})
it('轮询并复用真实工具进度，释放时取消运行请求',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'running'}),wordAIStatus:vi.fn().mockImplementation(()=>new Promise(()=>{})),wordAIEvents:vi.fn(async(_id,onEvent)=>{onEvent({kind:'toolStarted',sequence:1,toolName:'read_blocks',toolCallId:'call'})}),wordAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('正在执行工具：读取文档内容块'))
 expect(api.wordAIStatus).toHaveBeenCalledWith('t',expect.any(AbortSignal))
 binding.dispose();expect(api.wordAICancel).toHaveBeenCalledWith(api.wordAIStart.mock.calls[0][0].clientRequestId);expect(root.querySelector('.native-word-assistant')).toBeNull()
})
it('同步待提交编辑后选区失效时拒绝请求，不得以空选区读取全文',()=>{
 const api={wordAIStart:vi.fn(),wordAICancel:vi.fn()};const {root,binding,setSelection,flush}=fixture(api);binding.open()
 const scope=root.querySelector<HTMLSelectElement>('[data-word-ai=scope]')!;scope.value='selection';scope.dispatchEvent(new Event('change'))
 flush.mockImplementationOnce(()=>setSelection([]));root.querySelector<HTMLButtonElement>('[data-word-ai=summarize]')!.click()
 expect(api.wordAIStart).not.toHaveBeenCalled();expect(root.textContent).toContain('选区无法可靠对应来源');binding.dispose()
})
it('展示服务端审阅读取边界及批注修订工具中文名称，不将边界当作HTML',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'review',status:'completed',result:{...result,limitations:['仅覆盖正文锚定审阅信息','<img src=x>不含图片审阅'],toolEvents:[{tool:'read_comments'},{tool:'read_revisions'}]}}),wordAICancel:vi.fn()}
 const {root,binding}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('仅覆盖正文锚定审阅信息'))
 expect(root.textContent).toContain('<img src=x>不含图片审阅');expect(root.querySelector('img')).toBeNull()
 expect(root.textContent).toContain('读取批注 → 读取修订');binding.dispose()
})
it('审阅覆盖与正文覆盖独立，批注和修订引用显示后端标签而不虚造块引用',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'review',status:'completed',result:{...result,coverage:{scope:'document',totalBlocks:1,fullyReadBlockIds:['b1'],scopeReadComplete:true},citations:[],reviewCoverage:{comments:{totalItems:2,fullyReadIds:['comment-id'],readComplete:false},revisions:{totalItems:1,fullyReadIds:['revision-id'],readComplete:true}},reviewCitations:[{kind:'comment',id:'comment-id',label:'批注：收入核验'},{kind:'revision',id:'revision-id',label:'修订：费用调整',blockId:'b1'}]}}),wordAICancel:vi.fn()}
 const {root,binding}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('批注实际完整读取：1 / 2；批注尚未读完可读取项'))
 expect(root.textContent).toContain('修订实际完整读取：1 / 1；修订已读完可读取项')
 expect(root.textContent).toContain('审阅引用：批注：收入核验');expect(root.textContent).toContain('审阅引用：修订：费用调整')
 expect(root.textContent).not.toContain('第 undefined 个内容块');expect(root.textContent).not.toContain('comment-id');binding.dispose()
})
it('零项投影即使完成也只声明可读取项，不宣称全部审阅均已读取',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'limited',status:'completed',result:{...result,limitations:['复杂修订不可读取；选区未提供批注锚点。'],reviewCoverage:{comments:{totalItems:0,fullyReadIds:[],readComplete:true},revisions:{totalItems:0,fullyReadIds:[],readComplete:true}}}}),wordAICancel:vi.fn()}
 const {root,binding}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('批注实际完整读取：0 / 0；批注已读完可读取项'))
 expect(root.textContent).toContain('修订实际完整读取：0 / 0；修订已读完可读取项')
 expect(root.textContent).toContain('复杂修订不可读取；选区未提供批注锚点。')
 expect(root.textContent).not.toContain('全部审阅已读完');binding.dispose()
})
it('新对话清除回答和进度，保留输入，并忽略已取消任务的迟到回执',async()=>{
 let finish!:(value:object)=>void
 const api={
  wordAIStart:vi.fn().mockResolvedValueOnce({taskId:'first',status:'completed',result})
   .mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve})),
  wordAICancel:vi.fn().mockResolvedValue({status:'cancelled'}),
 }
 const {root,binding}=fixture(api)
 binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('文档总结'))
 const reset=root.querySelector<HTMLButtonElement>('button[aria-label="新对话"]')!
 const input=root.querySelector('textarea')!
 input.value='还没发送的问题'
 reset.click()
 expect(root.textContent).not.toContain('文档总结')
 expect(input.value).toBe('还没发送的问题')
 expect(document.activeElement).toBe(input)
 expect(reset.hidden).toBe(true)
 binding.open('keyPoints')
 const request=api.wordAIStart.mock.calls[1][0].clientRequestId
 reset.click()
 expect(api.wordAICancel).toHaveBeenCalledWith(request)
 finish({taskId:'late',status:'completed',result})
 await Promise.resolve()
 await Promise.resolve()
 expect(root.textContent).not.toContain('文档总结')
 expect(input.value).toBe('还没发送的问题')
 binding.dispose()
})

it('同一文档连续阅读保留各轮问题、回答和引用，新对话清空记录', async () => {
 const api={
  wordAIStart:vi.fn()
   .mockResolvedValueOnce({taskId:'one',status:'completed',result:{...result,answer:'第一轮回答'}})
   .mockResolvedValueOnce({taskId:'two',status:'completed',result:{...result,answer:'第二轮回答'}}),
  wordAICancel:vi.fn(),
 }
 const {root,binding}=fixture(api)
 binding.open()
 const input=root.querySelector('textarea')!
 const send=root.querySelector<HTMLButtonElement>('[data-word-ai=start]')!
 for(const question of ['第一轮问题','第二轮问题']){
  input.value=question
  input.dispatchEvent(new Event('input'))
  send.click()
  await vi.waitFor(()=>expect(send.disabled).toBe(false))
 }
 const turns=[...root.querySelectorAll('.native-ai-transcript article')]
 expect(turns).toHaveLength(2)
 for(const [index,label] of ['第一轮','第二轮'].entries()){
  expect(turns[index]!.textContent).toContain(label+'问题')
  expect(turns[index]!.textContent).toContain(label+'回答')
  expect(turns[index]!.textContent).toContain('引用：第 1 个内容块')
 }
 root.querySelector<HTMLButtonElement>('[aria-label="新对话"]')!.click()
 expect(root.querySelector('.native-ai-transcript article')).toBeNull()
 binding.dispose()
})
it('review summary preset opens a read-only question without starting work until the user clicks read',async()=>{
 const api={wordAIStart:vi.fn().mockResolvedValue({taskId:'summary',status:'completed',result}),wordAICancel:vi.fn()}
 const {root,binding,draft}=fixture(api);binding.openPrompt('总结所有待处理修订，不接受或拒绝任何修订。')
 expect(root.querySelector('textarea')!.value).toContain('修订');expect(api.wordAIStart).not.toHaveBeenCalled();root.querySelector<HTMLButtonElement>('[data-word-ai=start]')!.click();await vi.waitFor(()=>expect(api.wordAIStart).toHaveBeenCalled());expect(api.wordAIStart.mock.calls[0][0]).toMatchObject({action:'ask',selection:[],instruction:'总结所有待处理修订，不接受或拒绝任何修订。'});expect(draft.operations).toEqual([]);binding.dispose()
})

it('queues Enter while reading and continues after an explicit resume following Stop', async () => {
  const api = {
    wordAIStart: vi.fn().mockImplementationOnce(() => new Promise(() => {})).mockResolvedValue({taskId:'queued',status:'failed'}),
    wordAICancel: vi.fn().mockResolvedValue({status:'cancelled'}),
  }
  const {root,binding} = fixture(api)
  binding.open('summarize')
  await vi.waitFor(()=>expect(api.wordAIStart).toHaveBeenCalledOnce())
  const input=root.querySelector('textarea')!
  input.value='第二条'
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))
  expect(input.value).toBe('')
  await vi.waitFor(()=>expect(root.querySelector('.ai-queue-toggle')?.textContent).toContain('1 条排队中'))
  root.querySelector<HTMLButtonElement>('[data-word-ai="cancel"]')!.click()
  await vi.waitFor(()=>expect(root.querySelector('.ai-queue-strip')?.getAttribute('data-paused')).toBe('true'))
  expect(api.wordAIStart).toHaveBeenCalledOnce()
  root.querySelector<HTMLButtonElement>('[aria-label="继续排队"]')!.click()
  await vi.waitFor(()=>expect(api.wordAIStart).toHaveBeenCalledTimes(2))
  expect(api.wordAIStart.mock.calls[1][0]).toMatchObject({instruction:'第二条',action:'summarize'})
  binding.dispose()
})
