import { afterEach, expect, it, vi } from 'vitest'
function getByLabelText(host: HTMLElement, label: string) { const value = [...host.querySelectorAll<HTMLElement>('[aria-label]')].find(x => x.getAttribute('aria-label') === label); if (!value) throw new Error(label); return value }
function getByRole(host: HTMLElement, role: string, options: {name: string}) { const value = [...host.querySelectorAll<HTMLButtonElement>(role)].find(x=>x.textContent===options.name); if (!value) throw new Error(options.name); return value }
const fireEvent = { input(node: HTMLElement, event: {target: {value:string}}) { (node as HTMLInputElement).value = event.target.value; node.dispatchEvent(new Event('input',{bubbles:true})) }, click(node: HTMLElement) { node.click() } }
const base = {enabled:false,provider:'tavily',model:'',baseUrl:'https://api.tavily.com',version:1,hasKey:true}
const catalog = {settings:{webSearch:base},catalog:{webSearch:[{id:'tavily',label:'Tavily',model:'',baseUrl:'https://api.tavily.com'}]},credentialStorageAvailable:true}
afterEach(()=>{vi.unstubAllGlobals();document.body.replaceChildren()})
it('密钥仅写入；保存失败保留草稿，重试成功后清空输入',async()=>{
  const {mountOfficeProviderSettings}=await import('./office-provider-settings')
  const host=document.createElement('div');document.body.append(host)
  let fail=true;const bodies:unknown[]=[]
  vi.stubGlobal('fetch',vi.fn(async(_url:string,options:RequestInit)=>{
    if(options.method==='GET')return new Response(JSON.stringify(catalog))
    bodies.push(JSON.parse(options.body as string))
    return fail?new Response(JSON.stringify({message:'服务暂不可用'}),{status:503}):new Response(JSON.stringify({...base,version:2}))
  }))
  const dirty=vi.fn();await mountOfficeProviderSettings(host,{capabilities:['webSearch'],onDirty:dirty,onBusy:()=>{}})
  const key=getByLabelText(host,'API Key') as HTMLInputElement
  expect(key.type).toBe('password');expect(key.value).toBe('')
  fireEvent.input(key,{target:{value:'new-secret'}})
  fireEvent.click(getByRole(host,'button',{name:'保存联网搜索'}))
  await vi.waitFor(()=>expect(host.textContent).toContain('服务暂不可用'))
  expect(key.value).toBe('new-secret');expect(dirty).toHaveBeenLastCalledWith(true)
  fail=false;fireEvent.click(getByRole(host,'button',{name:'保存联网搜索'}))
  await vi.waitFor(()=>expect(host.textContent).toContain('已保存'))
  expect((getByLabelText(host,'API Key') as HTMLInputElement).value).toBe('')
  expect(bodies[1]).toMatchObject({apiKey:'new-secret',expectedVersion:1})
  expect(dirty).toHaveBeenLastCalledWith(false)
})
it('测试使用未保存草稿并冻结编辑，返回后不把测试当成保存',async()=>{
  const {mountOfficeProviderSettings}=await import('./office-provider-settings')
  const host=document.createElement('div');document.body.append(host)
  let finish!:(r:Response)=>void;let path=''
  vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit)=>{
    if(options.method==='GET')return new Response(JSON.stringify(catalog))
    path=url;return await new Promise<Response>(resolve=>{finish=resolve})
  }))
  const dirty=vi.fn();await mountOfficeProviderSettings(host,{capabilities:['webSearch'],onDirty:dirty,onBusy:()=>{}})
  fireEvent.input(getByLabelText(host,'API Key'),{target:{value:'draft-key'}})
  fireEvent.click(getByRole(host,'button',{name:'测试联网搜索'}))
  expect((getByLabelText(host,'API Key') as HTMLInputElement).disabled).toBe(true)
  expect(path).toBe('/office/api/admin/providers/webSearch/test')
  finish(new Response(JSON.stringify({ok:true,message:'测试未保存配置'})))
  await vi.waitFor(()=>expect(host.textContent).toContain('测试未保存配置'))
  expect(dirty).toHaveBeenLastCalledWith(true)
  expect((getByLabelText(host,'API Key') as HTMLInputElement).value).toBe('draft-key')
})
