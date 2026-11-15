import {afterEach,expect,it,vi} from 'vitest'
import {bindNativePDFAssistant} from './native-pdf-assistant'
import {NativeDraft} from './native-draft'
import type {NativePDFNavigation} from './native-api'
afterEach(()=>{document.body.replaceChildren();localStorage.clear()})
function fixture(navigate:(target:NativePDFNavigation,current:()=>boolean)=>Promise<void>) {
 const root=document.createElement('div');document.body.append(root)
 const draft=new NativeDraft({documentId:'navigation',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 let view='p1'
 const result={answer:'已请求跳转',sourceSha256:'a'.repeat(64),navigation:{page:2,pageId:'p2'},citations:[],coverage:{pageCount:2,fullyReadPages:[]},toolEvents:[{tool:'goto_page'}]}
 const api={pdfAIStart:vi.fn(async(_payload:object)=>({taskId:'nav',status:'completed',result})),pdfAICancel:vi.fn(async()=>({}))}
 const binding=bindNativePDFAssistant(root,{api:api as never,draft,selection:()=>[],onNavigate:vi.fn(),viewPageId:()=>view,onReadNavigate:navigate})
 return {root,draft,result,api,binding,move:()=>{view='p3'}}
}
it('awaits actual host navigation before success and never writes the draft',async()=>{
 let finish!:()=>void
 const navigate=vi.fn((_target:NativePDFNavigation,_current:()=>boolean)=>new Promise<void>(resolve=>{finish=resolve}))
 const {root,api,binding,draft}=fixture(navigate)
 binding.open('summarize');await vi.waitFor(()=>expect(navigate).toHaveBeenCalledOnce())
 expect(api.pdfAIStart.mock.calls[0][0]).toMatchObject({viewPageId:'p1'})
 expect(root.querySelector('[role=status]')!.textContent).not.toContain('已定位')
 finish();await vi.waitFor(()=>expect(root.querySelector('[role=status]')!.textContent).toContain('已定位到第 2 页'))
 expect(draft.operations).toEqual([]);expect(draft.dirty).toBe(false);binding.dispose()
})
it('failed reveal preserves answer and reports failure without success',async()=>{
 const {root,binding}=fixture(async()=>{throw new Error('目标未显示')})
 binding.open('summarize');await vi.waitFor(()=>expect(root.querySelector('[role=status]')!.textContent).toContain('目标未显示'))
 expect(root.textContent).toContain('已请求跳转');expect(root.querySelector('[role=status]')!.textContent).not.toContain('已定位');binding.dispose()
})
it('changed reading page prevents late navigation while retaining the answer',async()=>{
 const navigate=vi.fn(async()=>{})
 const {root,binding,api,move,result}=fixture(navigate)
 api.pdfAIStart.mockImplementationOnce(async()=>{move();return {taskId:'nav',status:'completed',result}})
 binding.open('summarize');await vi.waitFor(()=>expect(root.querySelector('[role=status]')!.textContent).toContain('当前页面已变化'))
 expect(navigate).not.toHaveBeenCalled();expect(root.textContent).toContain('已请求跳转');binding.dispose()
})
it('cancel during navigation invalidates host guard and late UI success',async()=>{
 let finish!:()=>void,guard!:()=>boolean
 const {root,binding}=fixture(async(_target,current)=>{guard=current;await new Promise<void>(resolve=>{finish=resolve})})
 binding.open('summarize');await vi.waitFor(()=>expect(guard).toBeTypeOf('function'))
 root.querySelector<HTMLButtonElement>('[data-pdf-ai=cancel]')!.click();expect(guard()).toBe(false);finish()
 await new Promise(resolve=>setTimeout(resolve,20));expect(root.querySelector('[role=status]')!.textContent).not.toContain('已定位');binding.dispose()
})
