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
