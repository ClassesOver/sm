import { afterEach, expect, it, vi } from 'vitest'
import { bindNativeOfficeAssistant } from './native-office-assistant'
import { NativeDraft } from './native-draft'
afterEach(() => { document.body.replaceChildren(); localStorage.clear() })
function fixture(api: object) {
 const root=document.body.appendChild(document.createElement('div'))
 const draft=new NativeDraft({documentId:'word',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 let selected: unknown={sheetName:'数据',startRow:0,endRow:1,startColumn:0,endColumn:1};const flush=vi.fn()
 const binding=bindNativeOfficeAssistant(root,{api:api as never,draft,format:'xlsx',context:async scope=>{flush();return {operations:structuredClone(draft.operations),selection:scope==='selection' ? selected : null} as never}})
 return {root,draft,binding,flush,setSelection:(value:unknown)=>{selected=value}}
}
const result={answer:'<img src=x>文档总结',readingVersion:'draft',coverage:{scope:'document',totalBlocks:3,fullyReadBlockIds:['b1'],scopeReadComplete:false},sourceSha256:'a'.repeat(64),effectiveSha256:'b'.repeat(64),citations:[{label:'数据!A1:B2'}],issues:[{code:'incomplete',message:'尚未完整读取'}],toolEvents:[{tool:'read_cells'}],limitations:['仅为引擎已提取文字，不包含备注。']}
it('默认整篇、同步未保存编辑并只读展示真实覆盖',async()=>{
 const api={officeAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'completed',result}),officeAICancel:vi.fn()}
 const {root,draft,binding,flush}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('文档总结'))
 expect(flush).toHaveBeenCalled();expect(api.officeAIStart.mock.calls[0][0]).toMatchObject({action:'summarize',selection:null,operations:[]})
 expect(root.textContent).toContain('未保存草稿');expect(root.textContent).toContain('尚未完整读取');expect(root.textContent).toContain('1 / 3');expect(root.textContent).toContain('数据!A1:B2')
 expect(root.textContent).not.toContain('opaque-block-hash');expect(root.textContent).not.toContain('opaque-cell-hash');expect(root.textContent).toContain('已执行工具：读取单元格');expect(root.textContent).toContain('仅为引擎已提取文字，不包含备注。');expect(root.querySelector('img')).toBeNull();expect(root.querySelector('svg')).not.toBeNull();expect(draft.operations).toEqual([]);expect(draft.dirty).toBe(false);binding.dispose()
})
it('显式选区提交且选择变化丢弃迟到回答',async()=>{
 let finish!:(value:object)=>void
 const api={officeAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),officeAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding,setSelection}=fixture(api);binding.open()
 const scope=root.querySelector<HTMLSelectElement>('[data-office-ai=scope]')!;scope.value='selection';scope.dispatchEvent(new Event('change'))
 root.querySelector<HTMLButtonElement>('[data-office-ai=summarize]')!.click()
 await vi.waitFor(()=>expect(api.officeAIStart).toHaveBeenCalled());expect(api.officeAIStart.mock.calls[0][0].selection).toMatchObject({sheetName:'数据'})
 setSelection({sheetName:'其他',startRow:0,endRow:1,startColumn:0,endColumn:1});finish({taskId:'t',status:'completed',result})
 await vi.waitFor(()=>expect(root.textContent).toContain('草稿或选区已变化'));expect(root.textContent).not.toContain('文档总结');binding.dispose()
})
it('回执前关闭取消服务端任务并丢弃迟到结果',async()=>{
 let finish!:(value:object)=>void
 const api={officeAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),officeAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding}=fixture(api);binding.open('keyPoints');await vi.waitFor(()=>expect(api.officeAIStart).toHaveBeenCalled());const id=api.officeAIStart.mock.calls[0][0].clientRequestId
 root.querySelector<HTMLButtonElement>('[data-office-ai=close]')!.click();expect(api.officeAICancel).toHaveBeenCalledWith(id)
 finish({taskId:'late',status:'completed',result});await Promise.resolve();await Promise.resolve();expect(root.textContent).not.toContain('文档总结');binding.dispose()
})
it('空选区不回退全文，问答必须输入',async()=>{
 const api={officeAIStart:vi.fn(),officeAICancel:vi.fn()};const {root,binding,setSelection}=fixture(api);binding.open()
 expect(root.querySelector<HTMLButtonElement>('[data-office-ai=start]')!.disabled).toBe(true)
 setSelection(null);const scope=root.querySelector<HTMLSelectElement>('[data-office-ai=scope]')!;scope.value='selection';scope.dispatchEvent(new Event('change'))
 root.querySelector<HTMLButtonElement>('[data-office-ai=summarize]')!.click();await vi.waitFor(()=>expect(root.textContent).toContain('选区无法可靠对应来源'));expect(api.officeAIStart).not.toHaveBeenCalled();expect(root.textContent).toContain('选区无法可靠对应来源');binding.dispose()
})
it('读取同步后的草稿，运行期间变化不会展示旧回答',async()=>{
 let finish!:(value:object)=>void
 const api={officeAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),officeAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding,draft,flush}=fixture(api)
 flush.mockImplementationOnce(()=>draft.setOperations([{kind:'replaceText',blockId:'b1',text:'当前输入'}]))
 binding.open('summarize');await vi.waitFor(()=>expect(api.officeAIStart).toHaveBeenCalled());expect(api.officeAIStart.mock.calls[0][0].operations).toEqual(draft.operations)
 draft.setOperations([{kind:'replaceText',blockId:'b1',text:'又修改'}]);finish({taskId:'t',status:'completed',result})
 await vi.waitFor(()=>expect(root.textContent).toContain('草稿或选区已变化'));expect(root.textContent).not.toContain('文档总结');binding.dispose()
})
it('轮询并复用真实工具进度，释放时取消运行请求',async()=>{
 const api={officeAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'running'}),officeAIStatus:vi.fn().mockImplementation(()=>new Promise(()=>{})),officeAIEvents:vi.fn(async(_id,onEvent)=>{onEvent({kind:'toolStarted',sequence:1,toolName:'read_blocks',toolCallId:'call'})}),officeAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
 const {root,binding}=fixture(api);binding.open('summarize')
 await vi.waitFor(()=>expect(root.textContent).toContain('正在执行工具：读取文档内容块'))
 expect(api.officeAIStatus).toHaveBeenCalledWith('t',expect.any(AbortSignal))
 binding.dispose();expect(api.officeAICancel).toHaveBeenCalledWith(api.officeAIStart.mock.calls[0][0].clientRequestId);expect(root.querySelector('.native-office-assistant')).toBeNull()
})
it('同步待提交编辑后选区失效时拒绝请求，不得以空选区读取全文',async()=>{
 const api={officeAIStart:vi.fn(),officeAICancel:vi.fn()};const {root,binding,setSelection,flush}=fixture(api);binding.open()
 const scope=root.querySelector<HTMLSelectElement>('[data-office-ai=scope]')!;scope.value='selection';scope.dispatchEvent(new Event('change'))
 flush.mockImplementationOnce(()=>setSelection(null));root.querySelector<HTMLButtonElement>('[data-office-ai=summarize]')!.click()
 await vi.waitFor(()=>expect(root.textContent).toContain('选区无法可靠对应来源'));expect(api.officeAIStart).not.toHaveBeenCalled();expect(root.textContent).toContain('选区无法可靠对应来源');binding.dispose()
})
