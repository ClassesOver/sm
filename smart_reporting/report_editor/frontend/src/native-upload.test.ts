import {it,expect,vi} from 'vitest'
import {createNativeUploader} from './native-upload'

it('上传使用宿主提供的已签名工作区凭据，同文件失败重试保持requestId',async()=>{
  const root=document.createElement('div'), requests:FormData[]=[]
  const fetcher=vi.fn().mockImplementation(async(_url,options)=>{requests.push(options.body);return requests.length===1 ? new Response(JSON.stringify({detail:{message:'稍后重试'}}),{status:503}) : new Response(JSON.stringify({editor:{url:'/reports/v1/native/open/grant'}}))})
  vi.stubGlobal('fetch',fetcher)
  const binding=createNativeUploader(root,{getAuthorization:async()=>({thread:'trusted',capability:'signed'}),requestId:()=> 'stable-upload'})
  const file=new File(['%PDF-test'],'report.pdf',{type:'application/pdf'})
  const input=root.querySelector<HTMLInputElement>('input[type=file]')!
  Object.defineProperty(input,'files',{value:[file],configurable:true});input.dispatchEvent(new Event('change'))
  root.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  await vi.waitFor(()=>expect(root.textContent).toContain('稍后重试'))
  root.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  await vi.waitFor(()=>expect(root.querySelector('a')?.getAttribute('href')).toBe('/reports/v1/native/open/grant'))
  expect(requests[0].get('requestId')).toBe(requests[1].get('requestId'))
  expect(fetcher.mock.calls[0][1].headers).toMatchObject({'X-Workspace-Thread':'trusted','X-Workspace-Capability':'signed'})
  binding.dispose();vi.unstubAllGlobals()
})
