import {afterEach,expect,it,vi} from 'vitest'
import {NativeApiError} from './native-api'
import {mountSlidesNativeAI} from './slides-native-ai'
afterEach(()=>document.body.replaceChildren())
function fixture(){
 const host=document.body.appendChild(document.createElement('div'))
 const candidate={editId:'edit',status:'succeeded',snapshotSha256:'s',proposal:{summary:'标题候选',operations:[{kind:'editSlides',edits:[{slideIndex:0,elementId:'title',text:'新标题'}]}]}}
 const api={start:vi.fn().mockResolvedValue(candidate),status:vi.fn(),cancel:vi.fn().mockResolvedValue({}),cancelRequest:vi.fn().mockResolvedValue({}),accept:vi.fn().mockResolvedValue({operations:candidate.proposal.operations})},apply=vi.fn()
 const view=mountSlidesNativeAI(host,{api,locked:()=>false,apply,context:scope=>({expectedSha256:'a',operations:[],selection:[{slideIndex:0,elementId:'title'}],scope:scope==='deck'?'deck':'selection',label:'标题',objects:[{slideIndex:0,elementId:'title',text:'旧标题',name:'标题'}]})})
 const input=host.querySelector('textarea')!,scope=host.querySelector('select')!
 const submit=()=>{input.value='改标题';host.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))}
 return{host,api,view,input,scope,apply,submit,candidate}
}
it('编辑助手默认隐藏，真实图标中文标题，打开聚焦关闭取消且可重新打开',async()=>{
 const f=fixture();expect(f.view.panel.hidden).toBe(true);expect(f.view.panel.querySelector('.office-assistant-header svg')).not.toBeNull()
 f.view.open();expect(f.view.panel.hidden).toBe(false);expect(document.activeElement).toBe(f.input)
 f.submit();await vi.waitFor(()=>expect(f.host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
 f.view.close();expect(f.view.panel.hidden).toBe(true);expect(f.api.cancelRequest).toHaveBeenCalledOnce();expect(f.api.cancel).toHaveBeenCalledWith('edit')
 f.view.open();expect(f.view.panel.hidden).toBe(false);expect(f.view.panel.isConnected).toBe(true);expect(f.apply).not.toHaveBeenCalled();f.view.dispose()
})
it.each(['instruction','scope'])('修改%s废弃旧候选',async field=>{
 const f=fixture();f.view.open();f.submit();await vi.waitFor(()=>expect(f.host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
 if(field==='instruction'){f.input.value='不同要求';f.input.dispatchEvent(new Event('input'))}else{f.scope.value='deck';f.scope.dispatchEvent(new Event('change'))}
 f.host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click();expect(f.api.accept).not.toHaveBeenCalled();expect(f.host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(true);f.view.dispose()
})
it('采纳回执迟到关闭后不得写草稿',async()=>{
 const f=fixture();let finish!:(value:{operations:{kind:string}[]})=>void;f.api.accept.mockImplementation(()=>new Promise(resolve=>{finish=resolve}) as never)
 f.view.open();f.submit();await vi.waitFor(()=>expect(f.host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
 f.host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click();f.view.close();finish({operations:[{kind:'editSlides'}]})
 await Promise.resolve();await Promise.resolve();expect(f.apply).not.toHaveBeenCalled();f.view.dispose()
})

it('恢复请求携带原编辑身份和冻结授权', async () => {
 const f=fixture(), editId='a'.repeat(64)
 f.api.start.mockResolvedValueOnce({...f.candidate,editId,status:'running'}).mockResolvedValueOnce({...f.candidate,editId})
 f.api.status.mockRejectedValueOnce(new NativeApiError(404,'native_ai_job_missing','任务暂不可见'))
 f.view.open();f.submit()
 await vi.waitFor(()=>expect(f.host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
 expect(f.api.start.mock.calls[1][0]).toEqual({...f.api.start.mock.calls[0][0],resumeEditId:editId})
 expect(f.apply).not.toHaveBeenCalled()
 f.view.dispose()
})
