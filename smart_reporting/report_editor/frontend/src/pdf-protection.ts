import type {NativeSaveResponse} from './native-api'

export interface PdfProtectionRequest {
 requestId:string;expectedSha256:string;userPassword:string;ownerPassword:string
 permissions:{printing:boolean;modifying:boolean;annotating:boolean;copying:boolean}
}
export function bindPdfProtectionDialog(options:{root:HTMLElement;sourceSha256:string;unavailable:()=>string|null;submit:(payload:PdfProtectionRequest)=>Promise<NativeSaveResponse>}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog')
 dialog.className='pdf-layout-dialog';dialog.setAttribute('aria-label','保护 PDF')
 const title=owner.createElement('h3');title.textContent='创建密码保护 PDF'
 const hint=owner.createElement('p');hint.textContent='从已保存版本生成 AES-256 保护副本，仅提供独立下载。当前不支持修改或移除已有加密、表单及签名保护来源。密码仅用于本次请求，不进入草稿或操作历史。阅读器权限依赖阅读器遵守；所有者密码可解除限制，留空时沿用打开密码。'
 dialog.append(title,hint)
 function password(label:string){const row=owner.createElement('label'),input=owner.createElement('input');row.textContent=label;input.type='password';input.autocomplete='new-password';input.maxLength=127;input.setAttribute('aria-label',label);row.append(input);dialog.append(row);return input}
 const user=password('打开密码'),confirm=password('确认打开密码'),admin=password('所有者密码（可选）')
 const checks=new Map<keyof PdfProtectionRequest['permissions'],HTMLInputElement>()
 for(const[key,label]of [['printing','允许打印'],['modifying','允许修改'],['annotating','允许批注'],['copying','允许复制']]as const){const row=owner.createElement('label'),input=owner.createElement('input');input.type='checkbox';input.checked=true;input.dataset.permission=key;row.append(input,owner.createTextNode(label));dialog.append(row);checks.set(key,input)}
 const apply=owner.createElement('button');apply.type='button';apply.textContent='生成保护 PDF';apply.dataset.pdfProtectionApply=''
 const close=owner.createElement('button');close.type='button';close.textContent='关闭'
 const status=owner.createElement('p');status.setAttribute('role','status')
 const links=owner.createElement('div'),actions=owner.createElement('div');actions.className='pdf-layout-actions';actions.append(close,apply);dialog.append(status,links,actions);options.root.append(dialog)
 let disposed=false,busy=false,generation=0,cached:NativeSaveResponse|undefined
 const clear=()=>{user.value=confirm.value=admin.value=''}
 function show(result:NativeSaveResponse){
  status.textContent=(result.validation.ok?'验收通过':'PDF 已生成；验收未通过')+(result.validation.issues.length?'：'+result.validation.issues.map(issue=>issue.message||issue.code).join('；'):'')
  links.replaceChildren();const href=result.artifacts.pdf?.downloadUrl
  if(!href)return
  try{const url=new URL(href,owner.baseURI);if(!['http:','https:'].includes(url.protocol)||url.origin!==new URL(owner.baseURI).origin)return}catch{return}
  const link=owner.createElement('a');link.href=href;link.textContent='下载保护 PDF';link.rel='noopener';links.append(link)
 }
 async function submit(){
  if(disposed||busy||!dialog.open)return
  const reason=options.unavailable();if(reason){status.textContent=reason;return}
  if(!user.value||user.value!==confirm.value){status.textContent='打开密码不能为空，且两次输入必须一致';return}
  const valid=(value:string)=>new TextEncoder().encode(value).length<=127
  if(!valid(user.value)||!valid(admin.value)){status.textContent='密码不得超过 127 UTF-8 字节';return}
  const payload:PdfProtectionRequest={requestId:crypto.randomUUID(),expectedSha256:options.sourceSha256,userPassword:user.value,ownerPassword:admin.value||user.value,permissions:{printing:checks.get('printing')!.checked,modifying:checks.get('modifying')!.checked,annotating:checks.get('annotating')!.checked,copying:checks.get('copying')!.checked}}
  clear();const token=generation;busy=true;apply.disabled=true;for(const input of [user,confirm,admin,...checks.values()])input.disabled=true;links.replaceChildren();status.textContent='正在创建保护副本…'
  try{const result=await options.submit(payload);cached=result;if(!disposed&&dialog.open&&token===generation)show(result)}
  catch(error){if(!disposed&&dialog.open&&token===generation)status.textContent=error instanceof Error?error.message:String(error)}
  finally{payload.userPassword=payload.ownerPassword='';busy=false;if(!disposed){apply.disabled=false;for(const input of [user,confirm,admin,...checks.values()])input.disabled=false}}
 }
 apply.addEventListener('click',()=>{void submit()});close.addEventListener('click',()=>dialog.close())
 dialog.addEventListener('close',()=>{clear();generation++});dialog.addEventListener('cancel',clear)
 return {open(){if(disposed||busy||dialog.open||options.unavailable())return;generation++;clear();if(cached)show(cached);else{status.textContent='';links.replaceChildren()}dialog.showModal()},dispose(){if(disposed)return;disposed=true;generation++;clear();dialog.remove()}}
}
