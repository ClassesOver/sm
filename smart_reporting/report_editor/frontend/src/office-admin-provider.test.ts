import { expect, it, vi } from 'vitest'
it('媒体搜索切换保留未保存草稿并在保存时锁定导航',async()=>{
  document.body.innerHTML='<main id="office-admin"></main>'
  const config={enabled:false,provider:'tavily',model:'',baseUrl:'https://api.tavily.com',hasKey:false,version:0}
  let finish!:(response:Response)=>void
  vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit)=>{
    if(url.endsWith('/session'))return new Response(JSON.stringify({user:{user:'10',name:'Admin',role:'admin'},csrfToken:'token'}))
    if(url.endsWith('/admin/settings'))return new Response(JSON.stringify({version:0,modelId:'',imageModel:'',searchEnabled:true,integrationsEnabled:true}))
    if(options.method==='PUT')return await new Promise<Response>(resolve=>{finish=resolve})
    return new Response(JSON.stringify({settings:{webSearch:config},catalog:{webSearch:[{id:'tavily',label:'Tavily',model:'',baseUrl:config.baseUrl}]},credentialStorageAvailable:true}))
  }))
  vi.spyOn(window,'confirm').mockReturnValue(false)
  await import('./office-admin')
  const button=(label:string)=>[...document.querySelectorAll<HTMLButtonElement>('button')].find(x=>x.textContent===label)!
  await vi.waitFor(()=>expect(button('搜索')).toBeDefined());button('搜索').click()
  await vi.waitFor(()=>expect(document.querySelector('[aria-label="API Key"]')).not.toBeNull())
  const key=document.querySelector<HTMLInputElement>('[aria-label="API Key"]')!;key.value='secret';key.dispatchEvent(new Event('input',{bubbles:true}))
  button('模型配置').click();expect(window.confirm).toHaveBeenCalled();expect(key.isConnected).toBe(true)
  button('保存联网搜索').click();expect(button('模型配置').disabled).toBe(true)
  finish(new Response(JSON.stringify({...config,version:1,hasKey:true})))
  await vi.waitFor(()=>expect(button('模型配置').disabled).toBe(false))
  expect(document.querySelector<HTMLInputElement>('[aria-label="API Key"]')!.value).toBe('')
  vi.restoreAllMocks();vi.unstubAllGlobals();document.body.replaceChildren()
})
