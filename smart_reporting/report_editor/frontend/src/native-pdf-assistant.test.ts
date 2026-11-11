import { afterEach, expect, it, vi } from 'vitest'
import { bindNativePDFAssistant } from './native-pdf-assistant'
import { NativeDraft } from './native-draft'

afterEach(() => { document.body.replaceChildren(); localStorage.clear() })
function fixture(api: object) {
  const root = document.createElement('div'); document.body.append(root)
  const draft = new NativeDraft({ documentId:'read',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'db',companyId:'c',userId:'u',threadId:'t'} },localStorage)
  const binding = bindNativePDFAssistant(root, {api:api as never,draft,selection:()=>[],onNavigate:vi.fn()})
  return {root,draft,binding}
}
it('无选区总结保留只读草稿，回答按文字显示且展示真实覆盖和工具',async()=>{
  const api={pdfAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'completed',result:{answer:'<img src=x>只读总结',coverage:{pageCount:2,fullyReadPages:[1],scopeReadComplete:false},citations:[{pageNumber:1,pageId:'p1'}],issues:[{code:'incomplete',message:'尚未读完'}],toolEvents:[{tool:'read_pages'}]}}),pdfAICancel:vi.fn()}
  const {root,draft,binding}=fixture(api)
  binding.open('summarize')
  await vi.waitFor(()=>expect(root.textContent).toContain('只读总结'))
  expect(api.pdfAIStart.mock.calls[0][0]).toMatchObject({action:'summarize',selection:[],operations:[]})
  expect(root.querySelector('img')).toBeNull()
  expect(root.textContent).toContain('尚未读完')
  expect(root.textContent).toContain('read_pages')
  expect(draft.operations).toEqual([]);expect(draft.dirty).toBe(false)
  binding.dispose()
})
it('开始回执前取消按clientRequestId通知后端，迟到回答不展示',async()=>{
  let finish!:(value:object)=>void
  const api={pdfAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),pdfAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
  const {root,binding}=fixture(api)
  binding.open('keyPoints')
  const requestId=api.pdfAIStart.mock.calls[0][0].clientRequestId
  root.querySelector<HTMLButtonElement>('[data-pdf-ai=cancel]')!.click()
  await vi.waitFor(()=>expect(api.pdfAICancel).toHaveBeenCalledWith(requestId))
  finish({taskId:'late',status:'completed',result:{answer:'过期回答'}})
  await Promise.resolve();await Promise.resolve()
  expect(root.textContent).not.toContain('过期回答')
  binding.dispose()
})
it('卸载显式取消服务端运行任务',async()=>{
  const api={pdfAIStart:vi.fn().mockImplementation(()=>new Promise(()=>{})),pdfAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
  const {binding}=fixture(api)
  binding.open('summarize');binding.dispose()
  expect(api.pdfAICancel).toHaveBeenCalledWith(api.pdfAIStart.mock.calls[0][0].clientRequestId)
})
it('自由问答要求输入且不自动提交空问题',async()=>{
  const api={pdfAIStart:vi.fn(),pdfAICancel:vi.fn()}
  const {root,binding}=fixture(api)
  binding.open('ask');expect(api.pdfAIStart).not.toHaveBeenCalled()
  expect(root.querySelector<HTMLButtonElement>('[data-pdf-ai=start]')!.disabled).toBe(true)
  binding.dispose()
})
