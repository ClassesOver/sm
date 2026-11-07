import { it, expect, vi } from 'vitest'
import { bindNativeAI } from './native-ai'
import { NativeDraft } from './native-draft'

it('采纳时提交当前完整草稿，冲突保留修改且候选文字不作为HTML执行', async () => {
  const draft = new NativeDraft({ documentId: 'doc', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database:'db', companyId:'c', userId:'u', threadId:'t' } }, localStorage)
  const api = { aiStart: vi.fn().mockResolvedValue({editId:'id',status:'succeeded',snapshotSha256:'snapshot',proposal:{summary:'<img src=x>',operations:[]}}), aiAccept:vi.fn().mockRejectedValue(new Error('草稿已变化')), aiCancel:vi.fn() }
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
  const api = {aiStart:vi.fn().mockResolvedValue({editId:'id',status:'succeeded',snapshotSha256:'snapshot',proposal:{summary:'候选',operations:[]}}),aiAccept:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),aiCancel:vi.fn()}
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
