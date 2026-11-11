import { afterEach, expect, it, vi } from 'vitest'
import { mountSlidesNativeAI, type SlidesNativeAIClient } from './slides-native-ai'

afterEach(() => document.body.replaceChildren())
function fixture(api: object) {
  const host = document.createElement('div'); document.body.append(host)
  const view = mountSlidesNativeAI(host, {api:api as SlidesNativeAIClient, locked:()=>false, apply:vi.fn(),
    context:()=>({expectedSha256:'a'.repeat(64),operations:[],selection:[{slideIndex:0,elementId:'title'}],scope:'selection',label:'标题',objects:[{slideIndex:0,elementId:'title',text:'原文',name:'标题'}]})})
  const submit = () => {host.querySelector<HTMLTextAreaElement>('textarea')!.value='润色';host.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))}
  return {host,view,submit}
}
it('卸载后收到迟到的start身份仍取消服务器任务', async () => {
  let finish!: (value:object)=>void
  const api={start:vi.fn(()=>new Promise(resolve=>{finish=resolve})),status:vi.fn(),accept:vi.fn(),cancel:vi.fn().mockResolvedValue({})}
  const {view,submit}=fixture(api)
  submit();view.dispose()
  finish({editId:'late-server-task',status:'running',snapshotSha256:'s'.repeat(64)})
  await Promise.resolve();await Promise.resolve()
  expect(api.cancel).toHaveBeenCalledWith('late-server-task')
  expect(api.status).not.toHaveBeenCalled()
})
it('旧discard取消失败不得覆盖新候选成功状态', async () => {
  let rejectCancel!: (error:Error)=>void
  const succeeded={editId:'new-task',status:'succeeded',snapshotSha256:'s'.repeat(64),proposal:{summary:'新的候选',operations:[{kind:'editSlides',edits:[],order:[0]}]}}
  const api={start:vi.fn().mockResolvedValueOnce({editId:'old-task',status:'running',snapshotSha256:'s'.repeat(64)}).mockResolvedValueOnce(succeeded),
    status:vi.fn(()=>new Promise(()=>{})),accept:vi.fn(),cancel:vi.fn().mockResolvedValue({}).mockImplementationOnce(()=>new Promise((_,reject)=>{rejectCancel=reject}))}
  const {host,view,submit}=fixture(api)
  submit();await vi.waitFor(()=>expect(api.status).toHaveBeenCalled())
  host.querySelector<HTMLButtonElement>('.native-ai-cancel')!.click()
  submit();await vi.waitFor(()=>expect(host.querySelector('[role=status]')?.textContent).toContain('候选已经引擎核验'))
  rejectCancel(new Error('旧取消连接失败'))
  await Promise.resolve();await Promise.resolve()
  expect(host.querySelector('[role=status]')?.textContent).toContain('候选已经引擎核验')
  view.dispose()
})
