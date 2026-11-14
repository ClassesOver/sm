import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {bindPdfSplit} from './pdf-split'
import {createNativeApi,type NativeContext,type NativeSaveResponse} from './native-api'

beforeEach(()=>{
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{document.body.replaceChildren();vi.unstubAllGlobals()})

it.each(['saved','same-sha','foreign-scope'])('拆分来源授权顺序与身份核验：%s',async mode=>{
  const root=document.createElement('div');document.body.append(root)
  const context:NativeContext={documentId:'parent',revision:4,format:'pdf',parentRevision:null,origin:'upload',
    scope:{database:'db',companyId:'c',userId:'u',threadId:'t'},sourceFile:{path:'source.pdf',size:1,sha256:'a'.repeat(64),mediaType:'application/pdf'}}
  const nextSha=mode==='same-sha'?'a'.repeat(64):'b'.repeat(64)
  const saved:NativeSaveResponse={documentId:'parent',revision:5,parentRevision:4,revisionRegistered:true,
    artifacts:{pdf:{sha256:nextSha}},editor:{openUrl:'/reports/v1/native/open/new-grant'},validation:{ok:false,issues:[]}}
  const events:string[]=[],payloads:unknown[]=[]
  vi.stubGlobal('fetch',async(input:string|URL,init?:RequestInit)=>{
    const path=new URL(String(input),window.location.href).pathname;events.push(path)
    if(path==='/reports/v1/native/open/new-grant')return new Response('authorized')
    if(path==='/reports/v1/native/parent/5/api/context')return new Response(JSON.stringify({csrfToken:'next-csrf',context:{...context,revision:5,sourceFile:{...context.sourceFile,sha256:nextSha},scope:mode==='foreign-scope'?{...context.scope,userId:'other'}:context.scope}}))
    if(path==='/reports/v1/native/parent/5/api/split-pdf'){
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('next-csrf');payloads.push(JSON.parse(String(init?.body)))
      return new Response(JSON.stringify({source:{documentId:'parent',revision:5,sha256:nextSha},parts:[],chunkSize:1,validation:{ok:false,issues:[]}}))
    }
    throw new Error(`unexpected request ${path}`)
  })
  const release=vi.fn(),beginSplit=vi.fn(()=>release)
  const controller=bindPdfSplit({root,api:createNativeApi('parent',4,'old-csrf'),context,pageCount:()=>3,unavailable:()=>null,
    flushForFileOperation:async()=>{events.push('flush');return saved},beginSplit})
  controller.open();root.querySelector<HTMLButtonElement>('[data-pdf-split-apply]')!.click()
  if(mode==='foreign-scope'){
    await vi.waitFor(()=>expect(root.textContent).toContain('新修订来源身份不一致'))
    expect(payloads).toHaveLength(0);expect(beginSplit).not.toHaveBeenCalled()
  }else{
    await vi.waitFor(()=>expect(root.textContent).toContain('拆分结果'))
    expect(events).toEqual(['flush','/reports/v1/native/open/new-grant','/reports/v1/native/parent/5/api/context','/reports/v1/native/parent/5/api/split-pdf'])
    expect(payloads[0]).toMatchObject({expectedSha256:nextSha,chunkSize:1})
    expect(beginSplit).toHaveBeenCalledOnce();expect(release).toHaveBeenCalledOnce()
  }
  controller.dispose()
})
