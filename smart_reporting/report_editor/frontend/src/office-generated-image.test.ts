import { afterEach, expect, it, vi } from 'vitest'
vi.mock('./office-client',()=>({officeSession:vi.fn(async()=>({user:'u'})),officeRequest:vi.fn()}))
import { officeRequest } from './office-client'
afterEach(()=>{document.body.replaceChildren();vi.clearAllMocks()})
it('生成只展示预览，明确确认才插入；草稿变化使候选失效',async()=>{
  const {mountOfficeGeneratedImage}=await import('./office-generated-image')
  const host=document.createElement('div');document.body.append(host);let identity='doc:1:slide:0';const insert=vi.fn(async()=>{})
  vi.mocked(officeRequest).mockResolvedValue({previewDataUrl:'data:image/png;base64,aGVsbG8=',mediaType:'image/png'})
  mountOfficeGeneratedImage(host,{identity:()=>identity,insert})
  host.querySelector('textarea')!.value='A landscape'
  host.querySelector<HTMLButtonElement>('button[type=submit]')!.click()
  await vi.waitFor(()=>expect(host.querySelector('img')!.hidden).toBe(false))
  expect(insert).not.toHaveBeenCalled()
  identity='doc:1:slide:1';host.querySelector<HTMLButtonElement>('[data-insert]')!.click()
  await vi.waitFor(()=>expect(host.textContent).toContain('已变化'))
  expect(insert).not.toHaveBeenCalled()
  host.querySelector<HTMLButtonElement>('button[type=submit]')!.click()
  await vi.waitFor(()=>expect(host.querySelector<HTMLButtonElement>('[data-insert]')!.disabled).toBe(false))
  host.querySelector<HTMLButtonElement>('[data-insert]')!.click()
  await vi.waitFor(()=>expect(insert).toHaveBeenCalledTimes(1))
  expect(insert.mock.calls[0]).toEqual([expect.any(File),'doc:1:slide:1'])
})
it('请求返回前切换文档或退出不会展示旧候选',async()=>{
  const {mountOfficeGeneratedImage}=await import('./office-generated-image')
  const host=document.createElement('div');document.body.append(host);let current:string|undefined='doc:1'
  let finish!:(value:unknown)=>void
  vi.mocked(officeRequest).mockImplementation(async()=>await new Promise<unknown>(resolve=>{finish=resolve}) as never)
  mountOfficeGeneratedImage(host,{identity:()=>current,insert:async()=>{throw Error('must not insert')}})
  host.querySelector('textarea')!.value='A landscape';host.querySelector<HTMLButtonElement>('button[type=submit]')!.click()
  await vi.waitFor(()=>expect(finish).toBeDefined());current=undefined
  finish({previewDataUrl:'data:image/png;base64,aGVsbG8=',mediaType:'image/png'})
  await vi.waitFor(()=>expect(host.textContent).toContain('已变化'))
  expect(host.querySelector('img')!.hidden).toBe(true)
})
