import {afterEach,expect,it,vi} from 'vitest'
import {mountWorkbookNativeAI} from './workbook-native-ai'

afterEach(()=>document.body.replaceChildren())
function setup(){
 const host=document.createElement('div');document.body.append(host)
 const candidate={editId:'edit',status:'succeeded',snapshotSha256:'b'.repeat(64),proposal:{summary:'候选',operations:[]}}
 const api={start:vi.fn(async()=>candidate),status:vi.fn(async()=>candidate),accept:vi.fn(async()=>({operations:[]})),cancel:vi.fn(async()=>({})),cancelRequest:vi.fn(async()=>({}))}
 const apply=vi.fn(async()=>{})
 const view=mountWorkbookNativeAI(host,{api,apply,locked:()=>false,context:async scope=>({scope,expectedSha256:'a'.repeat(64),operations:[],selection:{sheetName:'Sheet',startRow:0,endRow:0,startColumn:0,endColumn:0},label:'Sheet!A1',cells:{}})})
 const input=host.querySelector('textarea')!,form=host.querySelector('form')!
 const submit=async()=>{input.value='填写';form.dispatchEvent(new Event('submit',{cancelable:true}));await vi.waitFor(()=>expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))}
 return{host,view,api,apply,input,submit}
}
it('默认隐藏，打开聚焦，中文关闭按钮取消任务且面板可重新打开',async()=>{
 const {host,view,api,input,submit}=setup()
 expect(view.panel.hidden).toBe(true);view.open();expect(view.panel.hidden).toBe(false);expect(document.activeElement).toBe(input)
 expect(host.querySelector('.office-assistant-header')?.textContent).toContain('AI 助手')
 await submit();host.querySelector<HTMLButtonElement>('.office-assistant-close')!.click()
 expect(view.panel.hidden).toBe(true);expect(api.cancelRequest).toHaveBeenCalledOnce();expect(api.cancel).toHaveBeenCalledWith('edit')
 view.open();expect(view.panel.isConnected).toBe(true);expect(view.panel.hidden).toBe(false);view.dispose()
})
it.each(['instruction','scope'])('候选完成后改变%s不能采纳旧候选',async target=>{
 const {host,view,api,apply,input,submit}=setup();view.open();await submit()
 if(target==='instruction'){input.value='另一个要求';input.dispatchEvent(new Event('input'))}
 else{const scope=host.querySelector('select')!;scope.value='workbook';scope.dispatchEvent(new Event('change'))}
 host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
 await Promise.resolve();expect(api.accept).not.toHaveBeenCalled();expect(apply).not.toHaveBeenCalled();view.dispose()
})
it('关闭等待中的任务保留面板并取消晚到任务，重新打开不会执行旧响应',async()=>{
 const {view,api,input,host,apply}=setup();let finish!:(job:Awaited<ReturnType<typeof api.start>>)=>void
 api.start.mockImplementationOnce(()=>new Promise(done=>{finish=done}))
 view.open();input.value='填写';host.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
 await vi.waitFor(()=>expect(api.start).toHaveBeenCalledOnce());view.close()
 expect(view.panel.hidden).toBe(true);expect(api.cancelRequest).toHaveBeenCalledOnce()
 view.open();finish({editId:'late',status:'running',snapshotSha256:'b'.repeat(64),proposal:{summary:'旧候选',operations:[]}})
 await vi.waitFor(()=>expect(api.cancel).toHaveBeenCalledWith('late'))
 expect(view.panel.hidden).toBe(false);expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(true);expect(apply).not.toHaveBeenCalled();view.dispose()
})
it('共享侧栏把输入置底并保留真实submit表单关联',async()=>{
 const {view,host,input,api}=setup();view.open()
 expect(view.panel.matches('.native-ai.native-ai-panel.office-assistant-layout')).toBe(true)
 expect(input.closest('.office-assistant-composer')).not.toBeNull()
 expect(host.querySelector('.office-assistant-body')).not.toBeNull()
 expect(host.querySelector('.office-assistant-toolbar select')).not.toBeNull()
 const submit=host.querySelector<HTMLButtonElement>('[type=submit]')!
 expect(submit.form).toBe(host.querySelector('form'))
 input.value='填写';submit.click();await vi.waitFor(()=>expect(api.start).toHaveBeenCalledOnce());view.dispose()
})
