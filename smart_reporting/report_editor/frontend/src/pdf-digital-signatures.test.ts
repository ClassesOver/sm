import {afterEach,expect,it,vi} from 'vitest'
import {bindPdfDigitalSignatures,type PdfDigitalSignatureModel} from './pdf-digital-signatures'

afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks()})
function model():PdfDigitalSignatureModel{return {sourceSha256:'a'.repeat(64),digitalSignatures:[{fieldName:'Signature1',pageIndex:1,kind:'signature',status:'untrusted',problems:['self-signed'],subFilter:'adbe.pkcs7.detached',signerName:'<img src=x onerror=alert(1)>',signingTimeSigned:false,coversWholeDocument:true,chain:[],trusted:false}],signatureVerification:{scope:'basic-integrity-only',trustPolicy:'none',readable:true,issues:[],revocationChecked:false,timestampsVerified:false}}}
it.each([[1,'不允许修改'],[2,'填写表单与签名'],[3,'填写表单、签名与批注']] as const)('认证级别 %i 显示可读标签，且不升级证书信任结论',async(level,label)=>{
 const current=model();current.digitalSignatures![0].certifiedLevel=level
 const control=bindPdfDigitalSignatures({owner:document,sourceSha256:current.sourceSha256,model:()=>current,unavailable:()=>null,onGoToPage:vi.fn(),status:vi.fn()})
 try{
  await control.open();await vi.waitFor(()=>expect(document.querySelector('.pdf-sig-card')).not.toBeNull())
  const row=[...document.querySelectorAll('.pdf-sig-card .pdf-prop-row')].find(row=>row.querySelector('em')?.textContent?.includes(label))
  expect(row?.querySelector('span')?.textContent).toBe('证书签名')
  expect(row?.querySelector('em')?.textContent).toBe('声明的认证级别：'+label)
  expect(document.querySelector('.pdf-sig-pill')?.textContent).toBe('完整，信任未建立')
 }finally{control.dispose()}
})
it('完整源卡片只读显示告警，安全文本、定位与关闭恢复焦点',async()=>{
 const root=document.createElement('div'),opener=document.createElement('button');root.append(opener);document.body.append(root);opener.focus()
 const navigate=vi.fn(),control=bindPdfDigitalSignatures({owner:document,sourceSha256:'a'.repeat(64),model,unavailable:()=>null,onGoToPage:navigate,status:vi.fn()})
 await control.open();await vi.waitFor(()=>expect(document.querySelector('.pdf-sig-card')).not.toBeNull())
 expect(document.body.textContent).toContain('完整，信任未建立');expect(document.body.textContent).toContain('未检查证书吊销')
 expect(document.querySelector('.pdf-sig-card img')).toBeNull();expect(document.body.textContent).toContain('<img src=x onerror=alert(1)>')
 const target=[...document.querySelectorAll<HTMLButtonElement>('.pdf-digital-signatures-dialog button')].find(button=>button.textContent?.includes('跳转'))!
 target.click();expect(navigate).toHaveBeenCalledExactlyOnceWith(1);expect(document.activeElement).toBe(opener)
 expect(document.querySelector('.pdf-digital-signatures-dialog')).toBeNull();control.dispose()
})
it('过期来源、未读取模型与预览不展示陈旧签名结论',async()=>{
 let current:PdfDigitalSignatureModel={...model(),sourceSha256:'b'.repeat(64)},reason:string|null=null;const status=vi.fn()
 const control=bindPdfDigitalSignatures({owner:document,sourceSha256:'a'.repeat(64),model:()=>current,unavailable:()=>reason,onGoToPage:vi.fn(),status})
 await control.open();expect(status.mock.lastCall?.[0]).toContain('来源');expect(document.querySelector('dialog')).toBeNull()
 current={sourceSha256:'a'.repeat(64)};await control.open();expect(status.mock.lastCall?.[0]).toContain('尚未')
 current=model();reason='请先返回已保存原稿';await control.open();expect(status.mock.lastCall?.[0]).toContain('返回')
 control.dispose();reason=null;await control.open();expect(document.querySelector('dialog')).toBeNull()
})
it('空清单和读取失败分别解释，Escape不改变文档',async()=>{
 let current:PdfDigitalSignatureModel={...model(),digitalSignatures:[]};const before=JSON.stringify(current)
 const control=bindPdfDigitalSignatures({owner:document,sourceSha256:'a'.repeat(64),model:()=>current,unavailable:()=>null,onGoToPage:vi.fn(),status:vi.fn()})
 await control.open();await vi.waitFor(()=>expect(document.body.textContent).toContain('没有已赋值的数字签名'))
 document.querySelector('dialog')!.dispatchEvent(new Event('cancel',{cancelable:true}));expect(document.querySelector('dialog')).toBeNull();expect(JSON.stringify(current)).toBe(before)
 current={...current,signatureVerification:{...current.signatureVerification!,readable:false,issues:['字段结构无法完整读取']}}
 await control.open();await vi.waitFor(()=>expect(document.body.textContent).toContain('字段结构无法完整读取'))
 expect(document.body.textContent).not.toContain('没有已赋值的数字签名');control.dispose()
})
it('打开后来源变化的迟到定位不导航，也不抛出全局事件错误',async()=>{
 let current=model();const navigate=vi.fn(),status=vi.fn()
 const control=bindPdfDigitalSignatures({owner:document,sourceSha256:'a'.repeat(64),model:()=>current,unavailable:()=>null,onGoToPage:navigate,status})
 await control.open();await vi.waitFor(()=>expect(document.querySelector('.pdf-sig-card')).not.toBeNull());current={...current,sourceSha256:'c'.repeat(64)}
 const target=[...document.querySelectorAll<HTMLButtonElement>('.pdf-digital-signatures-dialog button')].find(button=>button.textContent?.includes('跳转'))!
 target.click();expect(navigate).not.toHaveBeenCalled();expect(status.mock.lastCall?.[0]).toContain('来源');control.dispose()
})
it('只读来源可延迟读取，销毁后的迟到结果不会打开面板',async()=>{
 let current:PdfDigitalSignatureModel={sourceSha256:'a'.repeat(64)},resolve!:(value:PdfDigitalSignatureModel)=>void
 const load=vi.fn(()=>new Promise<PdfDigitalSignatureModel>(done=>{resolve=done}))
 const control=bindPdfDigitalSignatures({owner:document,sourceSha256:'a'.repeat(64),model:()=>current,load,unavailable:()=>null,onGoToPage:vi.fn(),status:vi.fn()})
 const opening=control.open();expect(load).toHaveBeenCalledOnce();current=model();control.dispose();resolve(current);await opening
 expect(document.querySelector('dialog')).toBeNull()
 const available=bindPdfDigitalSignatures({owner:document,sourceSha256:'a'.repeat(64),model:()=>({sourceSha256:'a'.repeat(64)}),load:async()=>model(),unavailable:()=>null,onGoToPage:vi.fn(),status:vi.fn()})
 await available.open();await vi.waitFor(()=>expect(document.querySelector('.pdf-sig-card')).not.toBeNull());available.dispose()
})
