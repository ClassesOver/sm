import {it,expect,vi} from 'vitest'
import {createNativeOfficeTransport} from './native-office-view'
import {NativeDraft} from './native-draft'
const context={context:{documentId:'doc',revision:1,format:'pptx',scope:{database:'d',companyId:'c',userId:'u',threadId:'t'},sourceFile:{sha256:'a'.repeat(64)}}} as never
it('PPTX人工编辑复用独立原生保存，失败重试requestId相同且不伪造报告',async()=>{
  localStorage.clear()
  const draft=new NativeDraft({documentId:'doc',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage,()=> 'stable')
  const result={revision:2,revisionRegistered:true,artifacts:{pptx:{downloadUrl:'/download'}},validation:{ok:false,issues:[]}}
  const api={save:vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(result)}
  const transport=createNativeOfficeTransport({api:api as never,context,draft})
  const payload={expectedSha256:'a'.repeat(64),edits:[{slideIndex:0,elementId:'shape',text:'修改'}],order:[0]}
  await expect(transport.slides('save',{method:'POST',body:JSON.stringify(payload)})).rejects.toThrow('network')
  expect(draft.closed).toBe(false)
  const saved=await transport.slides<{pptx:unknown}>('save',{method:'POST',body:JSON.stringify(payload)})
  expect(saved.pptx).toEqual(result.artifacts.pptx)
  expect(api.save.mock.calls[0][0]).toEqual(api.save.mock.calls[1][0])
  expect(api.save.mock.calls[1][0].operations[0]).toEqual({kind:'editSlides',edits:payload.edits,order:[0]})
  expect(draft.closed).toBe(true)
})

it('编辑关闭时仍挂载独立Excel原件阅读入口，不创建编辑画布或提交残留草稿',async()=>{
  const {createNativeOfficeView}=await import('./native-office-view')
  const host=document.createElement('div');host.id='app';host.innerHTML='<div class="toolbar-group-output"></div><main></main><button></button><span></span>';document.body.append(host)
  const draft=new NativeDraft({documentId:'doc',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
  draft.setOperations([{kind:'stale'}])
  const api={officeAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'failed',error:{message:'测试失败原因'}}),officeAICancel:vi.fn().mockResolvedValue({status:'cancelled'})}
  const shell={editor:host.querySelector('main'),save:host.querySelector('button'),statusLabel:host.querySelector('span')}
  const response={...context as object,editingEnabled:false,officeReadAIEnabled:true,context:{documentId:'doc',format:'xlsx',sourceFile:{sha256:'a'.repeat(64)}}}
  const view=await createNativeOfficeView(shell as never,{api:api as never,context:response as never,draft})
  expect(shell.editor?.textContent).toContain('已核验原件')
  expect(shell.editor?.querySelector('.workbook-grid')).toBeNull()
  host.querySelector<HTMLButtonElement>('[data-action=office-read-ai]')!.click()
  host.querySelector<HTMLButtonElement>('[data-office-ai=summarize]')!.click()
  await vi.waitFor(()=>expect(api.officeAIStart).toHaveBeenCalled())
  expect(api.officeAIStart.mock.calls[0][0]).toMatchObject({operations:[],selection:null})
  await vi.waitFor(()=>expect(host.textContent).toContain('测试失败原因'))
  view.dispose();expect(host.querySelector('.native-office-assistant')).toBeNull();host.remove();localStorage.clear()
})
