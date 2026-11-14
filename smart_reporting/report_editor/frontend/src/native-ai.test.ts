import { it, expect, vi } from 'vitest'
import { bindNativeAI } from './native-ai'
import { NativeDraft } from './native-draft'

it.each(['cancel', 'selection', 'dispose'])('启动回执未返回时通过请求身份取消：%s', async action => {
  const draft = new NativeDraft({documentId:'early-cancel-'+action,revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},sessionStorage)
  const api = {aiStart:vi.fn((_payload, signal: AbortSignal) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once:true})
  })), aiCancel:vi.fn(), aiCancelRequest:vi.fn().mockResolvedValue({})}
  const root=document.createElement('div'), binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh:vi.fn()},onDraftChange:vi.fn()})
  binding.setSelection([{blockId:'p1'}]); root.querySelector('textarea')!.value='修改'
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(() => expect(api.aiStart).toHaveBeenCalledOnce())
  const payload=api.aiStart.mock.calls[0][0] as {clientRequestId?:string}
  if(action==='cancel') root.querySelector<HTMLButtonElement>('[data-ai=cancel]')!.click()
  else if(action==='selection') binding.setSelection([{blockId:'p2'}])
  else binding.dispose()
  await vi.waitFor(() => expect(api.aiCancelRequest).toHaveBeenCalledOnce())
  expect(payload.clientRequestId).toEqual(expect.any(String))
  expect(api.aiCancelRequest).toHaveBeenCalledWith(payload.clientRequestId)
  expect(api.aiCancel).not.toHaveBeenCalled()
  expect(draft.operations).toEqual([])
  binding.dispose()
})

it('启动网络失败且没有编辑ID时按请求身份清理服务端任务', async () => {
  const draft = new NativeDraft({documentId:'start-network-error',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},sessionStorage)
  const api = {aiStart:vi.fn().mockRejectedValue(new Error('网络中断')),aiCancel:vi.fn(),aiCancelRequest:vi.fn().mockResolvedValue({})}
  const root=document.createElement('div'),binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh:vi.fn()},onDraftChange:vi.fn()})
  binding.setSelection([{blockId:'p'}]);root.querySelector('textarea')!.value='修改'
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(() => expect(api.aiCancelRequest).toHaveBeenCalledOnce())
  expect(api.aiCancelRequest).toHaveBeenCalledWith(api.aiStart.mock.calls[0][0].clientRequestId)
  expect(root.textContent).toContain('网络中断');expect(draft.operations).toEqual([])
  binding.dispose();expect(api.aiCancelRequest).toHaveBeenCalledOnce()
})

it('采纳时提交当前完整草稿，冲突保留修改且候选文字不作为HTML执行', async () => {
  const draft = new NativeDraft({ documentId: 'doc', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database:'db', companyId:'c', userId:'u', threadId:'t' } }, localStorage)
  const api = { aiStart: vi.fn().mockResolvedValue({editId:'id',status:'succeeded',snapshotSha256:'snapshot',proposal:{summary:'<img src=x>',operations:[]}}), aiAccept:vi.fn().mockRejectedValue(new Error('草稿已变化')), aiCancel:vi.fn().mockResolvedValue({}) }
  const root = document.createElement('div')
  const binding = bindNativeAI(root, {api:api as never,draft,view:{refresh:vi.fn()},onDraftChange:vi.fn()})
  binding.setSelection([{blockId:'p1'}])
  root.querySelector('textarea')!.value='修改这段'
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(()=>expect(root.textContent).toContain('<img src=x>'))
  expect(root.querySelector('img')).toBeNull()
  draft.setOperations([{kind:'replaceParagraph',blockId:'p2',text:'新草稿'}])
  root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click()
  await vi.waitFor(()=>expect(root.textContent).toContain('草稿已变化'))
  expect(api.aiAccept.mock.calls[0][1].operations).toEqual(draft.operations)
  expect(draft.operations).toHaveLength(1)
  binding.dispose()
})

it('采纳请求期间继续编辑时，响应不能覆盖新草稿', async () => {
  localStorage.clear()
  const draft = new NativeDraft({documentId:'race',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
  let finish!: (value: {operations:{kind:string}[]})=>void
  const api = {aiStart:vi.fn().mockResolvedValue({editId:'id',status:'succeeded',snapshotSha256:'snapshot',proposal:{summary:'候选',operations:[]}}),aiAccept:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),aiCancel:vi.fn().mockResolvedValue({})}
  const root=document.createElement('div'), refresh=vi.fn()
  const binding=bindNativeAI(root,{api:api as never,draft,view:{refresh},onDraftChange:vi.fn()})
  binding.setSelection([{blockId:'p'}]);root.querySelector('textarea')!.value='修改'
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false))
  root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click()
  draft.setOperations([{kind:'new-user-edit'}]);finish({operations:[{kind:'old-ai-edit'}]})
  await vi.waitFor(()=>expect(root.textContent).toContain('草稿已变化'))
  expect(draft.operations).toEqual([{kind:'new-user-edit'}]);expect(refresh).not.toHaveBeenCalled()
  binding.dispose()
})

it('显示 PDF 替换内容和跳过原因，切页后不可采纳旧建议', async () => {
  const draft = new NativeDraft({documentId:'pdf-ai',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},sessionStorage)
  const operation = {kind:'replaceText',pageId:'p1',objectId:'o1',newText:'<b>改后的金额</b>'}
  const api = {
    aiStart:vi.fn().mockResolvedValue({editId:'id',status:'succeeded',snapshotSha256:'snapshot',proposal:{summary:'建议',operations:[operation],issues:[{code:'native_ai_pdf_text_skipped',message:'超出原行，已保留原文'}]}}),
    aiAccept:vi.fn(), aiCancel:vi.fn().mockResolvedValue({}),
  }
  const root = document.createElement('div')
  const binding = bindNativeAI(root,{api:api as never,draft,format:'pdf',view:{refresh:vi.fn()},onDraftChange:vi.fn()})
  const select = [{pageId:'p1',objectId:'o1'}]
  binding.setSelection(select)
  root.querySelector('textarea')!.value = '改写'
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(() => expect(root.textContent).toContain('替换 PDF 原文'))
  expect(root.textContent).toContain(operation.newText)
  expect(root.querySelector('b')).toBeNull()
  expect(root.textContent).toContain('超出原行，已保留原文')
  expect(api.aiStart.mock.calls[0][0].selection).toEqual(select)
  binding.setSelection([])
  const accept = root.querySelector<HTMLButtonElement>('[data-ai=accept]')!
  expect(accept.disabled).toBe(true)
  accept.click()
  expect(api.aiAccept).not.toHaveBeenCalled()
  expect(draft.operations).toEqual([])
  binding.dispose()
})

it('显式审阅目标复用候选链，普通选择不扩大授权，返回正文可恢复选择',async()=>{
 localStorage.clear()
 const draft=new NativeDraft({documentId:'review-ai',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 const op={kind:'replyComment',text:'回复意见'}
 const api={aiStart:vi.fn().mockResolvedValue({editId:'review',status:'succeeded',snapshotSha256:'s',proposal:{summary:'根批注建议',operations:[op]}}),aiAccept:vi.fn().mockResolvedValue({operations:[op]}),aiCancel:vi.fn().mockResolvedValue({})}
 const root=document.createElement('div'),flush=vi.fn(),refresh=vi.fn()
 const binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh,flushPendingEdits:flush},onDraftChange:vi.fn()})
 binding.setSelection([{blockId:'ordinary'}]);binding.openReview({sourceId:'source',targetId:'root'})
 expect(api.aiStart).not.toHaveBeenCalled();expect(root.querySelector('textarea')!.value).toBe('')
 binding.setSelection([{blockId:'later'}]);root.querySelector('textarea')!.value='请回复此根批注'
 root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
 await vi.waitFor(()=>expect(api.aiStart).toHaveBeenCalled())
 expect(flush).toHaveBeenCalled();expect(api.aiStart.mock.calls[0][0].selection).toEqual([{sourceId:'source',targetId:'root'}])
 await vi.waitFor(()=>expect(root.textContent).toContain('回复批注'))
 expect(draft.operations).toEqual([])
 root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click()
 await vi.waitFor(()=>expect(draft.operations).toEqual([op]))
 root.querySelector<HTMLButtonElement>('[data-ai=body-selection]')!.click()
 root.querySelector('textarea')!.value='普通正文编辑';root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
 await vi.waitFor(()=>expect(api.aiStart).toHaveBeenCalledTimes(2))
 expect(api.aiStart.mock.calls[1][0].selection).toEqual([{blockId:'later'}]);binding.dispose()
})
it('切换审阅目标时丢弃迟到建议，不自动执行线程或修订决策',async()=>{
 localStorage.clear()
 const draft=new NativeDraft({documentId:'late-review',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 let finish!:(v:object)=>void
 const api={aiStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),aiCancel:vi.fn().mockResolvedValue({})}
 const root=document.createElement('div'),binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh:vi.fn()},onDraftChange:vi.fn()})
 binding.openReview({blockId:'p',revisionId:'first'},'接受此修订');root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
 binding.openReview({blockId:'p',revisionId:'second'})
 finish({editId:'late',status:'succeeded',proposal:{summary:'迟到建议',operations:[]}})
 await Promise.resolve();await Promise.resolve();expect(root.textContent).not.toContain('迟到建议')
 expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(true);expect(draft.operations).toEqual([]);binding.dispose()
})
it.each([
 [{kind:'resolveComment',done:false},'重新打开线程'],
 [{kind:'resolveTextRevision',action:'reject'},'拒绝此修订'],
] as const)('审阅候选预览明确实际决策%j',async(operation,label)=>{
 const draft=new NativeDraft({documentId:'decision-'+label,revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},sessionStorage)
 const api={aiStart:vi.fn().mockResolvedValue({editId:'decision',status:'succeeded',snapshotSha256:'s',proposal:{summary:'待核对',operations:[operation]}}),aiCancel:vi.fn().mockResolvedValue({})}
 const root=document.createElement('div'),binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh:vi.fn()},onDraftChange:vi.fn()})
 binding.openReview({sourceId:'s',targetId:'t'},'按要求处理');root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
 await vi.waitFor(()=>expect(root.querySelector('pre')?.textContent).toContain(label))
 expect(draft.operations).toEqual([]);binding.dispose()
})

it('注释使用显式身份授权、显示前后差异，普通正文选区不能扩大权限',async()=>{
 localStorage.clear()
 const draft=new NativeDraft({documentId:'notes-ai',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 const op={kind:'updateNote',noteKind:'footnote',noteId:'1',expectedNoteSha256:'n',text:'新的引用说明'}
 const api={aiStart:vi.fn().mockResolvedValue({editId:'notes',status:'succeeded',snapshotSha256:'s',proposal:{summary:'注释建议',operations:[op]}}),aiAccept:vi.fn().mockResolvedValue({operations:[op]}),aiCancel:vi.fn().mockResolvedValue({})}
 const root=document.createElement('div'),refresh=vi.fn()
 const binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh},onDraftChange:vi.fn()})
 binding.openNotes({selectionKind:'note',noteKind:'footnote',noteId:'1'},'修订引用说明','原引用说明<img>')
 binding.setSelection([{blockId:'unrelated'}]);root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
 await vi.waitFor(()=>expect(root.textContent).toContain('原文：原引用说明<img>'))
 expect(api.aiStart.mock.calls[0][0].selection).toEqual([{selectionKind:'note',noteKind:'footnote',noteId:'1'}])
 expect(root.textContent).toContain('候选：新的引用说明');expect(root.querySelector('img')).toBeNull();expect(draft.operations).toEqual([])
 root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click();await vi.waitFor(()=>expect(draft.operations).toEqual([op]));binding.dispose()
})
