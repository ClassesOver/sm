import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {bindPdfSplitDialog} from './pdf-split-dialog'
import type {NativePdfSplitResult} from './native-api'

beforeEach(()=>{
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks()})
const result:NativePdfSplitResult={source:{documentId:'new-source',revision:5,sha256:'b'.repeat(64)},chunkSize:2,
  parts:[{index:1,pages:[1,2],filename:'source-1.pdf',result:{documentId:'child',revision:1,parentRevision:null,revisionRegistered:false,
    artifacts:{pdf:{downloadUrl:'/verified/first',sha256:'c'.repeat(64),size:32}},validation:{ok:false,issues:[{code:'register',message:'登记失败，下载仍可用'}]}}},
  {index:2,pages:[3],filename:'source-2.pdf',error:{code:'unavailable',message:'实际文件无法读取'}}],
  validation:{ok:false,issues:[{code:'pending',message:'尚未执行业务验收'}]}}
function fixture(){
  const root=document.createElement('div');document.body.append(root)
  const split=vi.fn(async(_payload:{requestId:string;expectedSha256:string;chunkSize:number})=>result)
  const prepareSource=vi.fn(async()=>({sha256:'b'.repeat(64),split}))
  const view=bindPdfSplitDialog({root,pageCount:()=>3,unavailable:()=>null,prepareSource})
  return{root,view,split,prepareSource,input:root.querySelector('input')!,apply:root.querySelector<HTMLButtonElement>('[data-pdf-split-apply]')!}
}
it('先flush保存来源再提交新身份，并逐份保留下载及具体失败原因',async()=>{
  const f=fixture();f.view.open();f.input.value='2';f.apply.click()
  await vi.waitFor(()=>expect(f.root.querySelectorAll('a')).toHaveLength(1))
  expect(f.prepareSource).toHaveBeenCalledOnce()
  expect(f.split.mock.calls[0]?.[0]).toMatchObject({expectedSha256:'b'.repeat(64),chunkSize:2})
  expect(f.root.textContent).toContain('登记失败，下载仍可用')
  expect(f.root.textContent).toContain('实际文件无法读取')
  expect(f.root.textContent).toContain('尚未执行业务验收')
  expect(f.root.querySelector('a')?.getAttribute('download')).toBe('source-1.pdf')
  f.root.querySelector('dialog')!.close();f.view.open()
  expect(f.root.querySelectorAll('a')).toHaveLength(1);expect(f.split).toHaveBeenCalledOnce()
})
it.each(['0','3','4','1.5','1e0',''])('无效每份页数%s不保存也不派生',async value=>{
  const f=fixture();f.view.open();f.input.value=value;f.apply.click()
  await vi.waitFor(()=>expect(f.root.textContent).toContain('整数'))
  expect(f.prepareSource).not.toHaveBeenCalled();expect(f.split).not.toHaveBeenCalled()
})
it('保存或确认失败保留输入，未发送任何拆分请求',async()=>{
  const f=fixture();f.prepareSource.mockRejectedValueOnce(new Error('确认已取消'))
  f.view.open();f.input.value='2';f.apply.click()
  await vi.waitFor(()=>expect(f.root.textContent).toContain('确认已取消'))
  expect(f.input.value).toBe('2');expect(f.split).not.toHaveBeenCalled();expect(f.apply.disabled).toBe(false)
})
it('等待中关闭不会丢已生成结果，返回后可重开且不重复提交',async()=>{
  const f=fixture();let done!:(value:NativePdfSplitResult)=>void
  f.split.mockImplementation(()=>new Promise(resolve=>{done=resolve}))
  f.view.open();f.apply.click();await vi.waitFor(()=>expect(f.split).toHaveBeenCalledOnce())
  f.root.querySelector('dialog')!.close();done(result);await new Promise(resolve=>setTimeout(resolve,0));f.view.open()
  expect(f.root.querySelectorAll('a')).toHaveLength(1);expect(f.split).toHaveBeenCalledOnce()
})
