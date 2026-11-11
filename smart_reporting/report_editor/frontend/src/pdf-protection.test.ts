import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {bindPdfProtectionDialog,type PdfProtectionRequest} from './pdf-protection'

beforeEach(()=>{
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')}
 HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new Event('close'))}
})
afterEach(()=>{document.body.replaceChildren();localStorage.clear()})
function fixture(unavailable:()=>string|null=()=>null){
 const root=document.createElement('div');document.body.append(root)
 const sent:PdfProtectionRequest[]=[]
 const submit=vi.fn(async(payload:PdfProtectionRequest)=>{sent.push(structuredClone(payload));return {documentId:'protected',revision:1,parentRevision:null,revisionRegistered:false,artifacts:{pdf:{downloadUrl:'/download/protected.pdf'}},validation:{ok:false,issues:[{code:'review',message:'请核对实际文件'}]}}})
 const dialog=bindPdfProtectionDialog({root,sourceSha256:'a'.repeat(64),unavailable,submit})
 const fields=()=>root.querySelectorAll<HTMLInputElement>('input[type=password]')
 return {root,submit,sent,dialog,fields,apply:()=>root.querySelector<HTMLButtonElement>('[data-pdf-protection-apply]')!.click()}
}
it('sends ephemeral passwords outside draft and keeps a warning download visible',async()=>{
 const f=fixture();f.dialog.open();const fields=f.fields();fields[0].value=fields[1].value='reader-secret';fields[2].value='owner-secret'
 f.root.querySelector<HTMLInputElement>('[data-permission=copying]')!.checked=false
 f.apply();expect([...f.fields()].map(field=>field.value)).toEqual(['','',''])
 await vi.waitFor(()=>expect(f.root.querySelector('a')?.getAttribute('href')).toBe('/download/protected.pdf'))
 expect(f.sent[0]).toMatchObject({expectedSha256:'a'.repeat(64),userPassword:'reader-secret',ownerPassword:'owner-secret',permissions:{copying:false}})
 expect(f.submit.mock.calls[0][0].userPassword).toBe('')
 expect(f.root.textContent).toContain('请核对实际文件');expect(f.root.textContent).not.toContain('验收通过')
 expect(localStorage.length).toBe(0);expect(f.root.textContent).not.toContain('reader-secret')
})
it('rejects mismatched or overlength UTF8 passwords without an API call',()=>{
 const f=fixture();f.dialog.open();const p=f.fields();p[0].value='reader';p[1].value='different';f.apply();expect(f.submit).not.toHaveBeenCalled()
 p[0].value=p[1].value='密'.repeat(43);f.apply();expect(f.submit).not.toHaveBeenCalled()
})
it('clears credentials on cancel and cannot bypass a changed availability guard',()=>{
 let reason:string|null=null;const f=fixture(()=>reason);f.dialog.open();f.fields()[0].value='reader-secret'
 f.root.querySelector('dialog')!.close();expect([...f.fields()].every(input=>!input.value)).toBe(true)
 f.dialog.open();reason='请先保存';f.fields()[0].value=f.fields()[1].value='reader-secret';f.apply();expect(f.submit).not.toHaveBeenCalled()
 f.dialog.dispose();expect(f.root.querySelector('dialog')).toBeNull()
})
