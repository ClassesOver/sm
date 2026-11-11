import {afterEach,expect,it,vi} from 'vitest'
import {bindNativePDFReview} from './native-pdf-review'
import {NativeDraft} from './native-draft'

afterEach(()=>{document.body.replaceChildren();localStorage.clear()})
const base=[{kind:'rotatePage',pageId:'p1',delta:90}]
const additions=[{kind:'replaceText',pageId:'p1',objectId:'t1',newText:'Revenue 72'}, {kind:'replyNote',pageId:'p1',contents:'Changed to 72.',author:'AI Assistant'}]
const task={editId:'review',clientRequestId:'request',status:'succeeded',snapshotSha256:'b'.repeat(64),proposal:{operations:[...base,...additions],previewDigest:'c'.repeat(64),appliedOperationIndices:[0,1,2],skippedOperations:[],answer:'处理完成',coverage:{fullyReadPages:[1]},notes:[{contents:'<img>Change to 72.',author:'Reviewer',status:'previewApplied',reason:'已核验原文',operationIndices:[1],reply:{contents:'Changed to 72.',intent:'change'}}],issues:[]}}
function fixture(overrides:object={}) {
 const root=document.createElement('div');document.body.append(root)
 const draft=new NativeDraft({documentId:'pdf-review',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 draft.setOperations(base)
 const api={pdfReviewStart:vi.fn().mockResolvedValue(task),pdfReviewStatus:vi.fn(),pdfReviewAccept:vi.fn().mockResolvedValue({operations:[...base,...additions]}),pdfReviewCancel:vi.fn().mockResolvedValue({status:'cancelled'}),...overrides}
 const refresh=vi.fn().mockResolvedValue(undefined),changed=vi.fn()
 const binding=bindNativePDFReview(root,{api:api as never,draft,view:{refresh},onDraftChange:changed})
 const click=(id:string)=>root.querySelector<HTMLButtonElement>('[data-pdf-review='+id+']')!.click()
 return {root,draft,api,binding,refresh,changed,click}
}
it('整份批注建议先显示真实回执，显式采纳后只写一次完整base并支持撤销',async()=>{
 const {root,draft,api,binding,click,refresh}=fixture();binding.open();click('start')
 await vi.waitFor(()=>expect(root.textContent).toContain('处理完成'))
 expect(api.pdfReviewStart.mock.calls[0][0]).toMatchObject({operations:base,instruction:'',expectedSha256:'a'.repeat(64)})
 expect(draft.operations).toEqual(base);expect(root.querySelector('img')).toBeNull()
 expect(root.textContent).toContain('已在预览执行');expect(root.textContent).toContain('Changed to 72.')
 click('accept');await vi.waitFor(()=>expect(refresh).toHaveBeenCalledTimes(1))
 expect(draft.operations).toEqual([...base,...additions]);draft.undo();expect(draft.operations).toEqual(base)
 binding.dispose()
})
it('撤销全部草稿新增标注先明确展示回执，显式采纳空草稿并支持撤销重做',async()=>{
 const pendingBase=[{kind:'addTextAnnotation',pageId:'p1',rect:[30,100,50,118],text:'删除这条草稿标注'}]
 const pendingTask={...task,proposal:{...task.proposal,operations:[],appliedOperationIndices:[],removedBaseOperationIndices:[0],notes:[{contents:'删除这条草稿标注',status:'previewApplied',reason:'已撤销尚未保存的新增标注',operationIndices:[],removedBaseOperationIndices:[0]}]}}
 const {root,draft,binding,click,refresh,changed}=fixture({pdfReviewStart:vi.fn().mockResolvedValue(pendingTask),pdfReviewAccept:vi.fn().mockResolvedValue({operations:[]})})
 draft.setOperations(pendingBase);binding.open();click('start')
 await vi.waitFor(()=>expect(root.textContent).toContain('处理完成'))
 expect(root.querySelector('.native-ai-evidence > p')?.textContent).toContain('撤销草稿新增标注 1 项')
 expect(root.querySelector('.native-ai-evidence section')?.textContent).toContain('撤销草稿新增标注 1 项')
 expect(root.textContent).toContain('已执行 0 项')
 expect(draft.operations).toEqual(pendingBase);expect(changed).not.toHaveBeenCalled()
 click('accept');await vi.waitFor(()=>expect(refresh).toHaveBeenCalledTimes(1))
 expect(draft.operations).toEqual([])
 draft.undo();expect(draft.operations).toEqual(pendingBase)
 draft.redo();expect(draft.operations).toEqual([])
 binding.dispose()
})
it('采纳请求期间草稿变化，迟到候选不覆盖草稿',async()=>{
 let finish!:(v:object)=>void
 const {root,draft,binding,click,refresh}=fixture({pdfReviewAccept:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve}))})
 binding.open();click('start');await vi.waitFor(()=>expect(root.textContent).toContain('处理完成'))
 click('accept');draft.setOperations([...base,{kind:'rotatePage',pageId:'p1',delta:180}])
 finish({operations:[...base,...additions]});await vi.waitFor(()=>expect(root.textContent).toContain('草稿已变化'))
 expect(draft.operations).toHaveLength(2);expect(refresh).not.toHaveBeenCalled();binding.dispose()
})
it('开始回执之前关闭按request身份取消，迟到结果不显示',async()=>{
 let finish!:(v:object)=>void
 const {root,draft,api,binding,click}=fixture({pdfReviewStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve}))})
 binding.open();click('start');const id=api.pdfReviewStart.mock.calls[0][0].clientRequestId
 click('close');expect(api.pdfReviewCancel).toHaveBeenCalledWith(id)
 finish(task);await Promise.resolve();await Promise.resolve()
 expect(root.textContent).not.toContain('<img>');expect(draft.operations).toEqual(base);binding.dispose()
})
it('旧取消失败不能覆盖新任务状态；卸载也取消后端任务',async()=>{
 let reject!:(e:Error)=>void
 const {root,api,binding,click}=fixture({pdfReviewStart:vi.fn().mockImplementationOnce(()=>new Promise(()=>{})).mockResolvedValueOnce(task),pdfReviewCancel:vi.fn().mockImplementationOnce(()=>new Promise((_,r)=>{reject=r})).mockResolvedValue({status:'cancelled'})})
 binding.open();click('start');click('cancel');click('start')
 await vi.waitFor(()=>expect(root.textContent).toContain('处理完成'))
 reject(new Error('旧取消失败'));await Promise.resolve();await Promise.resolve()
 expect(root.textContent).not.toContain('旧取消失败');binding.dispose();expect(api.pdfReviewCancel).toHaveBeenCalledTimes(2)
})
it('候选已进入草稿后预览刷新失败，明确保留草稿并给出具体原因',async()=>{
 const {root,draft,binding,click,refresh}=fixture()
 refresh.mockRejectedValueOnce(new Error('实际预览刷新失败'))
 binding.open();click('start');await vi.waitFor(()=>expect(root.textContent).toContain('处理完成'));click('accept')
 await vi.waitFor(()=>expect(root.querySelector('[role=status]')?.textContent).toContain('已进入草稿'))
 expect(root.querySelector('[role=status]')?.textContent).toContain('实际预览刷新失败')
 expect(draft.operations).toEqual([...base,...additions]);binding.dispose()
})
