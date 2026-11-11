import type { NativeSaveResponse } from './native-api'
import { parsePdfExtractPages } from './pdf-extract-dialog'

export interface PdfExternalPagesRequest {
  requestId:string;expectedSha256:string;action:'insert'|'replace';externalSha256:string;bytesBase64:string
  afterPage?:number;pages?:number[]
}
const MAX_BYTES=6*1024*1024
export function bindPdfExternalPagesDialog(options:{
  root:HTMLElement;sourceSha256:string;pageCount:()=>number;currentPage:()=>number
  unavailable:()=>string|null;submit:(payload:PdfExternalPagesRequest)=>Promise<NativeSaveResponse>
}){
  const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog';dialog.setAttribute('aria-label','外部 PDF 页面')
  const title=owner.createElement('h3'),hint=owner.createElement('p')
  hint.textContent='选择不超过 6 MiB 的真实 PDF。双方须无表单、批注、保护或导航结构；外部文件全部页面按原顺序写入新修订。替换会在最早选中页的位置插入外部页面，其余选中页删除。原修订保留；不支持安全擦除。'
  const fileLabel=owner.createElement('label');fileLabel.textContent='外部 PDF 文件'
  const file=owner.createElement('input');file.type='file';file.accept='application/pdf,.pdf';file.setAttribute('aria-label','外部 PDF 文件');fileLabel.append(file)
  const afterLabel=owner.createElement('label');afterLabel.textContent='插入到父 PDF 第几页之后（0 为最前）'
  const after=owner.createElement('input');after.type='number';after.min='0';after.step='1';after.setAttribute('aria-label','插入父 PDF 页后');afterLabel.append(after)
  const pagesLabel=owner.createElement('label');pagesLabel.textContent='替换父 PDF 页码（例如 1,3-5）'
  const pages=owner.createElement('input');pages.type='text';pages.setAttribute('aria-label','替换父 PDF 页码');pagesLabel.append(pages)
  const apply=owner.createElement('button');apply.type='button';apply.textContent='生成新修订';apply.dataset.pdfExternalPagesApply=''
  const close=owner.createElement('button');close.type='button';close.textContent='关闭'
  const message=owner.createElement('p');message.setAttribute('role','status');const links=owner.createElement('div')
  dialog.append(title,hint,fileLabel,afterLabel,pagesLabel,apply,close,message,links);options.root.append(dialog)
  let action:'insert'|'replace'='insert',busy=false,disposed=false,generation=0,requestKey='',requestId='',cached:NativeSaveResponse|undefined
  function show(result:NativeSaveResponse){
    links.replaceChildren();message.textContent=`${result.validation.ok?'验收通过':'验收未通过，PDF 已生成'}${result.validation.issues.length?'：'+result.validation.issues.map(issue=>issue.message||issue.code).join('；'):''}`
    for(const [text,value]of [['下载新修订 PDF',result.artifacts.pdf?.downloadUrl],['打开新修订',result.editor?.openUrl]]){
      if(!value)continue
      try{const url=new URL(value,owner.baseURI);if(!['http:','https:'].includes(url.protocol)||url.origin!==new URL(owner.baseURI).origin)continue}catch{continue}
      const link=owner.createElement('a');link.textContent=text!;link.href=value;link.rel='noopener';links.append(link,owner.createTextNode(' '))
    }
  }
  const enable=(enabled:boolean)=>{apply.disabled=file.disabled=after.disabled=pages.disabled=!enabled}
  dialog.addEventListener('close',()=>{generation++});close.addEventListener('click',()=>dialog.close())
  file.addEventListener('change',()=>{cached=undefined;links.replaceChildren();message.textContent=''})
  apply.addEventListener('click',()=>{void submit()})
  async function submit(){
    if(disposed||busy||!dialog.open)return
    const blocked=options.unavailable();if(blocked){message.textContent=blocked;return}
    const picked=file.files?.[0];if(!picked||picked.size<1||picked.size>MAX_BYTES){message.textContent='请选择 1 字节至 6 MiB 的 PDF 文件';return}
    let position:{afterPage:number}|{pages:number[]}
    try{
      if(action==='insert'){const value=Number(after.value);if(!/^\d+$/.test(after.value)||!Number.isSafeInteger(value)||value<0||value>options.pageCount())throw Error('插入页码超出父 PDF 范围');position={afterPage:value}}
      else position={pages:parsePdfExtractPages(pages.value,options.pageCount())}
    }catch(error){message.textContent=error instanceof Error?error.message:String(error);return}
    const token=generation,chosenAction=action
    busy=true;enable(false);links.replaceChildren();message.textContent='正在校验上传文件并生成新修订…'
    try{
      const bytes=new Uint8Array(await picked.arrayBuffer())
      if(bytes.length!==picked.size||new TextDecoder().decode(bytes.subarray(0,5))!=='%PDF-')throw Error('外部文件不是有效 PDF')
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('')
      let binary='';for(let offset=0;offset<bytes.length;offset+=32768)binary+=String.fromCharCode(...bytes.subarray(offset,offset+32768))
      if(disposed||!dialog.open||generation!==token)return
      const reason=options.unavailable();if(reason)throw Error(reason)
      const key=JSON.stringify([chosenAction,digest,position])
      if(key!==requestKey){requestKey=key;requestId=crypto.randomUUID();cached=undefined}
      const result=await options.submit({requestId,expectedSha256:options.sourceSha256,action:chosenAction,externalSha256:digest,bytesBase64:btoa(binary),...position})
      cached=result
      if(!disposed&&dialog.open&&generation===token)show(result)
    }catch(error){if(!disposed&&dialog.open&&generation===token)message.textContent=error instanceof Error?error.message:String(error)}
    finally{busy=false;if(!disposed&&dialog.open&&generation===token)enable(true)}
  }
  return {
    open(next:'insert'|'replace'){
      if(disposed||busy||dialog.open||options.unavailable())return
      if(action!==next){cached=undefined;requestKey='';file.value=''}
      action=next;generation++;enable(true);title.textContent=next==='insert'?'插入外部 PDF 页面':'替换为外部 PDF 页面'
      afterLabel.hidden=next!=='insert';pagesLabel.hidden=next!=='replace';after.max=String(options.pageCount());after.value=String(options.currentPage());pages.value=String(options.currentPage())
      if(cached)show(cached);else{message.textContent='';links.replaceChildren()}
      dialog.showModal()
    },
    dispose(){if(disposed)return;disposed=true;generation++;dialog.remove()},
  }
}
