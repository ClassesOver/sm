import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {bindPdfConvertOfficeDialog} from './pdf-convert-office'

beforeEach(()=>{
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')}
 HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new Event('close'))}
})
afterEach(()=>document.body.replaceChildren())
function fixture(href='/download/converted.pptx'){
 const root=document.createElement('div');document.body.append(root)
 let blocked:string|null=null
 const submit=vi.fn(async()=>({documentId:'converted',revision:1,parentRevision:null,revisionRegistered:true,artifacts:{pptx:{downloadUrl:href}},editor:{openUrl:'/reports/v1/native/converted/1/open'},validation:{ok:false,issues:[{code:'manual_review',message:'请人工核对版式'}]},conversion:{warnings:['扫描页保留为图片']}}))
 const panel=bindPdfConvertOfficeDialog({root,sourceSha256:'a'.repeat(64),unavailable:()=>blocked,submit})
 return {root,panel,submit,block:(value:string)=>blocked=value,apply:()=>root.querySelector<HTMLButtonElement>('[data-pdf-convert-office-apply]')!.click()}
}
it('retains actual PPTX download while showing failed validation and conversion warnings',async()=>{
 const f=fixture();f.panel.open();f.apply();f.apply()
 await vi.waitFor(()=>expect(f.root.querySelector('a')?.getAttribute('href')).toBe('/download/converted.pptx'))
 expect(f.submit).toHaveBeenCalledTimes(1)
 expect(f.submit.mock.calls[0]).toEqual([{requestId:expect.any(String),expectedSha256:'a'.repeat(64),format:'pptx'}])
 expect(f.root.textContent).toContain('验收未通过');expect(f.root.textContent).toContain('请人工核对版式');expect(f.root.textContent).toContain('扫描页保留为图片')
 expect(f.root.querySelectorAll('a')).toHaveLength(2)
 f.panel.dispose();expect(f.root.querySelector('dialog')).toBeNull()
})
it('rechecks dirty guard and rejects cross origin download links',async()=>{
 const f=fixture('https://foreign.test/download.pptx');f.panel.open();f.block('请先保存');f.apply();expect(f.submit).not.toHaveBeenCalled()
 const second=fixture('https://foreign.test/download.pptx');second.panel.open();second.apply()
 await vi.waitFor(()=>expect(second.root.textContent).toContain('请人工核对版式'))
 expect(second.root.querySelectorAll('a')).toHaveLength(1)
})
it.each([['docx','word'],['xlsx','xlsx']] as const)('creates %s as a separate editable document with a warning download',async(format,artifact)=>{
 const root=document.createElement('div');document.body.append(root)
 const submit=vi.fn(async()=>({documentId:'child',revision:1,parentRevision:null,revisionRegistered:true,artifacts:{[artifact]:{downloadUrl:'/download/converted.'+format}},editor:{openUrl:'/reports/v1/native/child/1/open'},validation:{ok:false,issues:[{code:'manual_review',message:'请人工核对内容与版式'}]}}))
 const panel=bindPdfConvertOfficeDialog({root,sourceSha256:'a'.repeat(64),unavailable:()=>null,submit})
 panel.open(format)
 root.querySelector<HTMLButtonElement>('[data-pdf-convert-office-apply]')!.click()
 await vi.waitFor(()=>expect(root.querySelector('a')?.getAttribute('href')).toBe('/download/converted.'+format))
 expect(submit.mock.calls[0]).toEqual([{requestId:expect.any(String),expectedSha256:'a'.repeat(64),format}])
 expect(root.textContent).toContain(format.toUpperCase()+' 已生成');expect(root.textContent).toContain('验收未通过')
 panel.dispose()
})
