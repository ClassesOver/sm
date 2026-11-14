import {afterEach,beforeEach,expect,it} from 'vitest'
import {bindPdfProtectionDialog,type PdfProtectionRequest} from './pdf-protection'
import type {NativeSaveResponse} from './native-api'

beforeEach(()=>{
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')}
 HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new Event('close'))}
})
afterEach(()=>document.body.replaceChildren())

function fixture(){
 const root=document.createElement('div');document.body.append(root)
 let resolve!:(result:NativeSaveResponse)=>void,reject!:(error:Error)=>void
 const pending=new Promise<NativeSaveResponse>((yes,no)=>{resolve=yes;reject=no})
 const sent:PdfProtectionRequest[]=[]
 const binding=bindPdfProtectionDialog({root,sourceSha256:'a'.repeat(64),unavailable:()=>null,submit:payload=>{sent.push(structuredClone(payload));return pending}})
 const passwords=()=>[...root.querySelectorAll<HTMLInputElement>('input[type=password]')]
 const permissions=()=>[...root.querySelectorAll<HTMLInputElement>('input[type=checkbox]')]
 const dialog=root.querySelector('dialog')!,apply=root.querySelector<HTMLButtonElement>('[data-pdf-protection-apply]')!
 binding.open();passwords()[0]!.value=passwords()[1]!.value='reader-secret'
 permissions()[3]!.checked=false
 return {root,binding,dialog,apply,passwords,permissions,sent,resolve,reject}
}
const result:NativeSaveResponse={documentId:'protected',revision:1,parentRevision:null,revisionRegistered:false,artifacts:{pdf:{downloadUrl:'/download/protected.pdf'}},validation:{ok:false,issues:[{code:'review',message:'请核对实际文件'}]}}

it('freezes submitted permissions and credentials until the protection request settles',async()=>{
 const f=fixture();f.apply.click()
 expect(f.permissions().every(input=>input.disabled)).toBe(true)
 expect(f.passwords().every(input=>input.disabled&&!input.value)).toBe(true)
 f.permissions()[3]!.click();expect(f.permissions()[3]!.checked).toBe(false)
 expect(f.sent[0]!.permissions).toEqual({printing:true,modifying:true,annotating:true,copying:false})
 f.resolve(result);await pendingUi()
 expect([...f.passwords(),...f.permissions(),f.apply].every(input=>!input.disabled)).toBe(true)
 expect(f.permissions()[3]!.checked).toBe(false)
 expect(f.root.querySelector('a')?.getAttribute('href')).toBe('/download/protected.pdf')
 expect(f.root.textContent).toContain('请核对实际文件');f.binding.dispose()
})
it('restores controls after failure without changing the submitted permissions',async()=>{
 const f=fixture();f.apply.click()
 expect([...f.passwords(),...f.permissions()].every(input=>input.disabled)).toBe(true)
 f.reject(new Error('保护副本生成失败，请重试'));await pendingUi()
 expect([...f.passwords(),...f.permissions(),f.apply].every(input=>!input.disabled)).toBe(true)
 expect(f.root.querySelector('[role=status]')?.textContent).toBe('保护副本生成失败，请重试')
 expect(f.permissions().map(input=>input.checked)).toEqual([true,true,true,false])
 expect(f.passwords().map(input=>input.value)).toEqual(['','','']);f.binding.dispose()
})
it('keeps close available while pending and reopens with cleared credentials and retained result',async()=>{
 const f=fixture();f.apply.click()
 expect(f.passwords().every(input=>input.disabled)).toBe(true)
 const close=[...f.root.querySelectorAll('button')].find(button=>button.textContent==='关闭')!
 expect(close.disabled).toBe(false);close.click();expect(f.dialog.open).toBe(false)
 f.resolve(result);await pendingUi();f.binding.open()
 expect(f.dialog.open).toBe(true)
 expect([...f.passwords(),...f.permissions(),f.apply].every(input=>!input.disabled)).toBe(true)
 expect(f.passwords().map(input=>input.value)).toEqual(['','',''])
 expect(f.permissions().map(input=>input.checked)).toEqual([true,true,true,false])
 expect(f.root.querySelector('a')?.getAttribute('href')).toBe('/download/protected.pdf');f.binding.dispose()
})
async function pendingUi(){await Promise.resolve();await Promise.resolve()}
