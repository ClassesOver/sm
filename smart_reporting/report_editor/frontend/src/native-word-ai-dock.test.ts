import { beforeEach, expect, it, vi } from 'vitest'
import { bindNativeAI } from './native-ai'
import { NativeDraft } from './native-draft'

beforeEach(() => { localStorage.clear(); document.body.replaceChildren() })
function setup(format: 'docx' | 'pdf' = 'docx') {
  const root = document.createElement('div'); document.body.append(root)
  const draft = new NativeDraft({documentId:'word-dock',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
  const operation = {kind:'replaceParagraph',blockId:'p',text:'已核对的修改'}
  const api = {aiStart:vi.fn().mockResolvedValue({editId:'edit',status:'succeeded',snapshotSha256:'snapshot',proposal:{summary:'候选建议',operations:[operation]}}),aiAccept:vi.fn().mockResolvedValue({operations:[operation]}),aiCancel:vi.fn().mockResolvedValue({})}
  const binding = bindNativeAI(root,{api:api as never,draft,format,view:{refresh:vi.fn()},onDraftChange:vi.fn()})
  binding.setSelection([{blockId:'p'}])
  const panel = root.querySelector<HTMLElement>('.native-ai')!
  return {root,panel,draft,api,binding,operation}
}
it('Word 默认收起且普通/审阅入口可打开；PDF 保持原有可见状态', () => {
  const word=setup()
  expect(word.panel.hidden).toBe(true)
  expect(word.root.querySelector('[data-ai=close] svg')).not.toBeNull()
  word.binding.open();expect(word.panel.hidden).toBe(false)
  word.root.querySelector<HTMLButtonElement>('[data-ai=close]')!.click();expect(word.panel.hidden).toBe(true)
  word.binding.openReview({sourceId:'s',targetId:'t'});expect(word.panel.hidden).toBe(false)
  word.panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(word.panel.hidden).toBe(true)
  word.binding.dispose()
  const pdf=setup('pdf');expect(pdf.panel.hidden).toBe(false);expect(pdf.root.querySelector('[data-ai=close]')).toBeNull();pdf.binding.dispose()
})
it('关闭中止启动等待，迟到编辑 ID 仅取消，不显示或写入草稿', async () => {
  const {root,panel,draft,api,binding}=setup()
  let finish!: (value: object) => void
  api.aiStart.mockImplementation(() => new Promise(resolve => {finish=resolve}) as never)
  binding.open();root.querySelector('textarea')!.value='改写此段';root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  const signal=api.aiStart.mock.calls[0][1] as AbortSignal
  binding.close();expect(signal.aborted).toBe(true);expect(api.aiCancel).not.toHaveBeenCalled()
  finish({editId:'late',status:'succeeded',proposal:{summary:'迟到候选',operations:[]}})
  await vi.waitFor(()=>expect(api.aiCancel).toHaveBeenCalledWith('late'))
  expect(panel.hidden).toBe(true);expect(root.textContent).not.toContain('迟到候选');expect(draft.operations).toEqual([])
  binding.open();expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(true);binding.dispose()
})
it('Word 预览建议仍需显式采纳；关闭后旧候选不可采纳', async () => {
  const {root,draft,api,binding,operation}=setup()
  binding.open();root.querySelector('textarea')!.value='改写此段';root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false))
  expect(draft.operations).toEqual([]);expect(api.aiAccept).not.toHaveBeenCalled()
  binding.close();expect(api.aiCancel).toHaveBeenCalledWith('edit');binding.open()
  root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click();expect(api.aiAccept).not.toHaveBeenCalled()
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false))
  root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click()
  await vi.waitFor(()=>expect(draft.operations).toEqual([operation]));binding.dispose()
})
it('Word 冻结修改要求，输入事件取消等待，程序化变更也不能采纳旧候选', async () => {
  const {root,draft,api,binding}=setup()
  const input=root.querySelector('textarea')!,start=root.querySelector<HTMLButtonElement>('[data-ai=start]')!,accept=root.querySelector<HTMLButtonElement>('[data-ai=accept]')!
  binding.open();input.value='原要求';start.click()
  await vi.waitFor(()=>expect(accept.disabled).toBe(false))
  input.value='变化后的要求';accept.click()
  expect(api.aiAccept).not.toHaveBeenCalled();expect(accept.disabled).toBe(true);expect(draft.operations).toEqual([])
  let finish!: (value:object)=>void
  api.aiStart.mockImplementation(()=>new Promise(resolve=>{finish=resolve}) as never)
  start.click();const signal=api.aiStart.mock.calls.at(-1)![1] as AbortSignal
  input.value='再次变化';input.dispatchEvent(new Event('input',{bubbles:true}));expect(signal.aborted).toBe(true)
  finish({editId:'late-input',status:'succeeded',proposal:{summary:'失效要求',operations:[]}})
  await vi.waitFor(()=>expect(api.aiCancel).toHaveBeenCalledWith('late-input'))
  expect(root.textContent).not.toContain('失效要求');expect(accept.disabled).toBe(true);binding.dispose()
})
it('Word 冻结选区，变化后取消候选及采纳等待，审阅授权仍保持原目标', async () => {
  const {root,draft,api,binding,operation}=setup()
  const input=root.querySelector('textarea')!,start=root.querySelector<HTMLButtonElement>('[data-ai=start]')!,accept=root.querySelector<HTMLButtonElement>('[data-ai=accept]')!
  binding.open();input.value='改写';start.click();await vi.waitFor(()=>expect(accept.disabled).toBe(false))
  binding.setSelection([{blockId:'next'}]);expect(accept.disabled).toBe(true);expect(api.aiCancel).toHaveBeenCalledWith('edit')
  start.click();await vi.waitFor(()=>expect(accept.disabled).toBe(false))
  let finish!: (value:{operations:typeof operation[]})=>void
  api.aiAccept.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  accept.click();binding.setSelection([{blockId:'last'}]);finish({operations:[operation]})
  await Promise.resolve();await Promise.resolve();expect(draft.operations).toEqual([]);expect(accept.disabled).toBe(true)
  binding.openReview({sourceId:'s',targetId:'review'},'请回复');start.click();await vi.waitFor(()=>expect(accept.disabled).toBe(false))
  binding.setSelection([{blockId:'unrelated'}]);expect(accept.disabled).toBe(false)
  expect(api.aiStart.mock.calls.at(-1)![0].selection).toEqual([{sourceId:'s',targetId:'review'}]);binding.dispose()
})
it('Word 共享外壳保持固定标题、中间候选区和底部输入操作区', async () => {
  const {panel,binding}=setup()
  binding.openReview({sourceId:'s',targetId:'t'},'请回复')
  await Promise.resolve()
  expect([...panel.children].map(node=>node.className)).toEqual(['office-assistant-header','office-assistant-toolbar','office-assistant-body','office-assistant-composer'])
  expect(panel.querySelector('.office-assistant-header h3')?.textContent).toBe('Word AI 编辑')
  expect(panel.querySelector('.office-assistant-header [data-ai=close] svg')).not.toBeNull()
  for(const selector of ['[data-ai=accept]','[data-ai=body-selection]','[role=status]','details','[aria-label="AI 执行进度"]'])expect(panel.querySelector('.office-assistant-body '+selector)).not.toBeNull()
  for(const selector of ['textarea','[data-ai=start]','[data-ai=cancel]'])expect(panel.querySelector('.office-assistant-composer '+selector)).not.toBeNull()
  binding.dispose()
})
it('Word review preset freezes authorized targets, requires generate then explicit accept, and rejects changed drafts',async()=>{
 const {root,draft,api,binding,operation}=setup()
 binding.openPreset('翻译成英语',[{blockId:'p'}],'selection')
 expect(root.querySelector('textarea')!.value).toBe('翻译成英语');expect(api.aiStart).not.toHaveBeenCalled()
 root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
 await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false))
 expect(api.aiStart.mock.calls[0][0].selection).toEqual([{blockId:'p'}]);expect(draft.operations).toEqual([])
 draft.setOperations([{...operation,text:'手工改稿'}])
 root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click()
 expect(api.aiAccept).not.toHaveBeenCalled();expect(draft.operations[0].text).toBe('手工改稿');binding.dispose()
})
it('Word preset selection changes invalidate the authorization until the preset is reopened',async()=>{
 const {root,api,binding}=setup();binding.openPreset('校对',[{blockId:'p'}],'selection');binding.setSelection([{blockId:'other'}]);root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();expect(api.aiStart).not.toHaveBeenCalled();binding.dispose()
})
it('Word flushes pending editor input before accepting a candidate and rejects a changed snapshot',async()=>{
 const {root,draft,api,binding,operation}=setup();binding.openPreset('校对',[{blockId:'p'}],'document');root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false))
 // A view may still hold a DOM input not yet reflected in NativeDraft.
 const pending={...operation,text:'待同步输入'}
 const editorInput=document.createElement('input');root.append(editorInput);editorInput.value='待同步输入'
 // The production contract calls view.flushPendingEdits, exercised in a dedicated binding.
 binding.dispose()
 const nextRoot=document.createElement('div');document.body.append(nextRoot)
 let pendingEdit=false
 const second=bindNativeAI(nextRoot,{api:api as never,draft,format:'docx',view:{refresh:vi.fn(),flushPendingEdits:()=>{if(pendingEdit)draft.setOperations([pending])}},onDraftChange:vi.fn()})
 second.openPreset('校对',[{blockId:'p'}],'document');nextRoot.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();await vi.waitFor(()=>expect(nextRoot.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false));pendingEdit=true
 nextRoot.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click();await Promise.resolve()
 expect(api.aiAccept).not.toHaveBeenCalled();expect(draft.operations).toEqual([pending]);second.dispose()
})
it('Word rejects results generated against a changed draft and cancels the remote candidate',async()=>{
 const {root,draft,api,binding,operation}=setup();let finish!:(value:object)=>void;api.aiStart.mockImplementation(()=>new Promise(resolve=>{finish=resolve}) as never)
 binding.openPreset('翻译',[{blockId:'p'}],'document');root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();draft.setOperations([{...operation,text:'生成期间编辑'}]);finish({editId:'late-draft',status:'succeeded',proposal:{summary:'旧草稿候选',operations:[]}})
 await vi.waitFor(()=>expect(api.aiCancel).toHaveBeenCalledWith('late-draft'));expect(root.textContent).not.toContain('旧草稿候选');binding.dispose()
})
it('Word rechecks preset authorization after pending-input flush changes selection',()=>{
 const base=setup();base.binding.dispose();const {api,draft}=base,root=document.body.appendChild(document.createElement('div'))
 let binding:ReturnType<typeof bindNativeAI>
 binding=bindNativeAI(root,{api:api as never,draft,format:'docx',view:{refresh:vi.fn(),flushPendingEdits:()=>binding.setSelection([{blockId:'other'}])},onDraftChange:vi.fn()})
 binding.setSelection([{blockId:'p'}]);binding.openPreset('校对',[{blockId:'p'}],'selection');root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();expect(api.aiStart).not.toHaveBeenCalled();binding.dispose()
})
it('Word rechecks editing locks after pending-input flush on generation and adoption',async()=>{
 const base=setup();base.binding.dispose();const {api,draft}=base,root=document.body.appendChild(document.createElement('div'));let lock=false,flushLock=true
 const binding=bindNativeAI(root,{api:api as never,draft,format:'docx',locked:()=>lock,view:{refresh:vi.fn(),flushPendingEdits:()=>{if(flushLock)lock=true}},onDraftChange:vi.fn()})
 binding.openPreset('校对',[{blockId:'p'}],'document');root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();expect(api.aiStart).not.toHaveBeenCalled()
 lock=false;flushLock=false;binding.update();root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click();await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false));flushLock=true
 root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click();expect(api.aiAccept).not.toHaveBeenCalled();binding.dispose()
})
