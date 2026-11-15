import {afterEach,expect,it,vi} from 'vitest'
import {mountWorkbookNativeAI, type WorkbookNativeAIClient} from './workbook-native-ai'
import {NativeApiError} from './native-api'

afterEach(()=>document.body.replaceChildren())
function setup(cells: Record<string, {value?: unknown; formula?: string}> = {}){
 const host=document.createElement('div');document.body.append(host)
 const candidate={editId:'edit',status:'succeeded',snapshotSha256:'b'.repeat(64),proposal:{summary:'候选',operations:[]}}
 const api={start:vi.fn<WorkbookNativeAIClient['start']>(async()=>candidate),status:vi.fn(async()=>candidate),accept:vi.fn(async()=>({operations:[]})),cancel:vi.fn(async()=>({})),cancelRequest:vi.fn(async()=>({}))}
 const apply=vi.fn(async()=>{})
 const view=mountWorkbookNativeAI(host,{api,apply,locked:()=>false,context:async scope=>({scope,expectedSha256:'a'.repeat(64),operations:[],selection:{sheetName:'Sheet',startRow:0,endRow:0,startColumn:0,endColumn:0},label:'Sheet!A1',cells})})
 const input=host.querySelector('textarea')!,form=host.querySelector('form')!
 const submit=async()=>{input.value='填写';form.dispatchEvent(new Event('submit',{cancelable:true}));await vi.waitFor(()=>expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))}
 return{host,view,api,apply,input,submit}
}
it('runs a source translation prompt against the original range and requires acceptance', async () => {
 const { view, api, host, apply } = setup({A1:{value:'hello'}})
 const operations = [{kind:'applyCellEdits',edits:[{sheetName:'Sheet',row:0,column:0,writeValue:true,cell:{value:'こんにちは'}}]}]
 api.start.mockResolvedValueOnce({...await api.status(),proposal:{summary:'日语译文',operations}})
 host.querySelector('select')!.value = 'workbook'
 view.translate('日本語')
 await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
 expect(api.start.mock.calls[0]?.[0]).toMatchObject({
  scope:'range', selection:{sheetName:'Sheet',startRow:0,endRow:0,startColumn:0,endColumn:0},
  instruction:expect.stringContaining('把当前选中区域的文本翻译成日本語'),
 })
 expect(apply).not.toHaveBeenCalled()
 host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
 await vi.waitFor(() => expect(apply).toHaveBeenCalledOnce())
 view.dispose()
})
it('rejects a translation candidate for a selected formula with a textual result', async () => {
 const { view, api, host, apply } = setup({A1:{value:'hello',formula:'"hello"'}})
 const operations = [{kind:'applyCellEdits',edits:[{sheetName:'Sheet',row:0,column:0,writeValue:true,cell:{value:'こんにちは'}}]}]
 api.start.mockResolvedValueOnce({...await api.status(),proposal:{summary:'日语译文',operations}})
 view.translate('日本語')
 await vi.waitFor(() => expect(host.querySelector('.native-ai-status')?.textContent).toContain('只能替换选区内原有的普通文本'))
 expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(true)
 expect(api.accept).not.toHaveBeenCalled()
 expect(apply).not.toHaveBeenCalled()
 view.dispose()
})
it('identifies the target sheet and rectangle before accepting a large clear', async () => {
 const {view,api,host,apply,submit}=setup()
 const operations=[{kind:'clearCellRange',sheetName:'Sheet',range:'A1:B1200'}]
 api.start.mockResolvedValueOnce({...await api.status(),proposal:{summary:'清空旧数据',operations}})
 view.open()
 await submit()
 expect(host.querySelector('.native-ai-preview li')?.textContent).toBe('Sheet!A1:B1200 · 清空值和公式，保留格式')
 expect(apply).not.toHaveBeenCalled()
 view.dispose()
})
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
it('服务重启后复用冻结请求，候选仍须显式采纳', async () => {
 const {view, api, host, submit, apply} = setup()
 const candidate = {...await api.status(), editId: 'a'.repeat(64)}
 api.start.mockResolvedValueOnce({...candidate, status: 'running'})
 api.start.mockResolvedValueOnce(candidate)
 api.status.mockRejectedValueOnce(new NativeApiError(404, 'native_ai_job_missing', '任务当前不可见'))
 view.open()
 await submit()
 expect(api.start).toHaveBeenCalledTimes(2)
 expect(api.start.mock.calls[1][0]).toEqual({...api.start.mock.calls[0][0], resumeEditId:candidate.editId})
 expect(api.cancelRequest).not.toHaveBeenCalled()
 expect(apply).not.toHaveBeenCalled()
 host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
 await vi.waitFor(() => expect(apply).toHaveBeenCalledOnce())
 view.dispose()
})
