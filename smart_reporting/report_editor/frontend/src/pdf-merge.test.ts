import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {webcrypto} from 'node:crypto'
import {bindPdfMerge} from './pdf-merge'
import {createNativeApi,type NativeContext,type NativeSaveResponse} from './native-api'

beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto)
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{document.body.replaceChildren();vi.unstubAllGlobals()})
it.each(['saved','same-sha','foreign-scope','unregistered'])('合并仅从实际保存后授权的新来源提交：%s',async mode=>{
  const root=document.body.appendChild(document.createElement('div'))
  const context:NativeContext={documentId:'parent',revision:4,format:'pdf',parentRevision:null,origin:'upload',scope:{database:'db',companyId:'c',userId:'u',threadId:'t'},sourceFile:{path:'source.pdf',size:1,sha256:'a'.repeat(64),mediaType:'application/pdf'}}
  const sha=mode==='same-sha'?'a'.repeat(64):'b'.repeat(64)
  const saved:NativeSaveResponse={documentId:'parent',revision:5,parentRevision:4,revisionRegistered:mode!=='unregistered',artifacts:{pdf:{sha256:sha}},editor:{openUrl:'/reports/v1/native/open/new-grant'},validation:{ok:false,issues:[]}}
  const events:string[]=[],payloads:unknown[]=[]
  vi.stubGlobal('fetch',async(input:string|URL,init?:RequestInit)=>{
    const path=new URL(String(input),window.location.href).pathname;events.push(path)
    if(path==='/reports/v1/native/open/new-grant')return new Response('authorized')
    if(path==='/reports/v1/native/parent/5/api/context')return new Response(JSON.stringify({csrfToken:'new-csrf',context:{...context,revision:5,sourceFile:{...context.sourceFile,sha256:sha},scope:mode==='foreign-scope'?{...context.scope,userId:'other'}:context.scope}}))
    if(path==='/reports/v1/native/parent/5/api/merge-pdf'){
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('new-csrf');payloads.push(JSON.parse(String(init?.body)))
      return new Response(JSON.stringify({documentId:'child',revision:1,revisionRegistered:false,artifacts:{pdf:{downloadUrl:'/verified/merged'}},validation:{ok:false,issues:[]}}))
    }
    throw Error(`unexpected ${path}`)
  })
  const release=vi.fn(),beginMerge=vi.fn(()=>release)
  const view=bindPdfMerge({root,context,api:createNativeApi('parent',4,'old-csrf'),unavailable:()=>null,flushForFileOperation:async()=>{events.push('flush');return saved},beginMerge})
  view.open();const file=root.querySelector('input')!,bytes=new TextEncoder().encode('%PDF-external')
  Object.defineProperty(file,'files',{value:[{name:'external.pdf',size:bytes.length,arrayBuffer:async()=>bytes.buffer}]});file.dispatchEvent(new Event('change'));root.querySelector<HTMLButtonElement>('[data-pdf-merge-apply]')!.click()
  if(mode==='foreign-scope'||mode==='unregistered'){
    await vi.waitFor(()=>expect(root.textContent).toContain(mode==='foreign-scope'?'新修订来源身份不一致':'新修订授权尚不可用'))
    expect(payloads).toHaveLength(0);expect(beginMerge).not.toHaveBeenCalled()
  }else{
    await vi.waitFor(()=>expect(root.querySelector('a')).not.toBeNull())
    expect(events).toEqual(['flush','/reports/v1/native/open/new-grant','/reports/v1/native/parent/5/api/context','/reports/v1/native/parent/5/api/merge-pdf'])
    expect(payloads[0]).toMatchObject({expectedSha256:sha});expect(beginMerge).toHaveBeenCalledOnce();expect(release).toHaveBeenCalledOnce()
  }
  view.dispose()
})
