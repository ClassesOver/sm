import type { PdfConvertOfficeRequest, PdfConvertOfficeResult } from './pdf-convert-office'
export type PdfTextExportFormat='markdown'|'html'
export type PdfTextOfficeResult=PdfConvertOfficeResult&{source?:{sha256:string}}
export interface PdfTextExportOptions{
  root:HTMLElement;sourceSha256:string;unavailable:()=>string|null
  convertOffice:(payload:PdfConvertOfficeRequest)=>Promise<PdfTextOfficeResult>
  fetchFile?:(url:string)=>Promise<Response>
}
export async function verifiedPdfTextDocx(result:PdfTextOfficeResult,sourceSha256:string,baseUri:string,fetchFile:(url:string)=>Promise<Response>){
  const artifact=result.artifacts.word
  if(result.source?.sha256!==sourceSha256||!artifact?.downloadUrl||!Number.isSafeInteger(artifact.size)||artifact.size!<=0||artifact.size!>64*1024*1024||!artifact.sha256||!/^[a-f0-9]{64}$/.test(artifact.sha256))throw Error('派生 Word 来源或文件身份无效')
  const url=new URL(artifact.downloadUrl,baseUri)
  if(!['http:','https:'].includes(url.protocol)||url.origin!==new URL(baseUri).origin)throw Error('派生 Word 下载地址无效')
  const response=await fetchFile(url.href)
  if(!response.ok)throw Error('派生 Word 下载失败；已生成的 Word 下载链接仍可使用')
  if(response.url&&new URL(response.url,baseUri).origin!==url.origin)throw Error('派生 Word 下载重定向地址无效')
  const content=await response.arrayBuffer()
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',content)),value=>value.toString(16).padStart(2,'0')).join('')
  const bytes=new Uint8Array(content)
  if(content.byteLength!==artifact.size||digest!==artifact.sha256||bytes[0]!==80||bytes[1]!==75||bytes[2]!==3||bytes[3]!==4)throw Error('派生 Word 实际文件身份不匹配')
  return bytes
}
export function bindPdfExportTextDialog(options:PdfTextExportOptions){
  const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog'
  const title=owner.createElement('h3'),hint=owner.createElement('p'),apply=owner.createElement('button'),close=owner.createElement('button'),status=owner.createElement('p'),links=owner.createElement('div')
  hint.textContent='先生成并核验独立 Word，再使用 GenOffice 文档序列化导出。扫描页保留图片，不执行 OCR；内容、字体和版式需人工核对。'
  apply.type=close.type='button';apply.dataset.pdfExportTextApply='';close.textContent='关闭';status.setAttribute('role','status')
  const actions=owner.createElement('div');actions.className='pdf-layout-actions';actions.append(close,apply)
  dialog.append(title,hint,status,links,actions);options.root.append(dialog)
  let disposed=false,busy=false,generation=0,format:PdfTextExportFormat='markdown',blobUrl:string|undefined
  function release(){if(blobUrl){URL.revokeObjectURL(blobUrl);blobUrl=undefined}links.replaceChildren()}
  function wordLink(result:PdfTextOfficeResult){const href=result.artifacts.word?.downloadUrl;if(!href)return;try{const url=new URL(href,owner.baseURI);if(url.origin!==new URL(owner.baseURI).origin||!['http:','https:'].includes(url.protocol))return;const link=owner.createElement('a');link.href=url.href;link.textContent='下载已生成的 Word';link.rel='noopener';links.append(link)}catch{}}
  dialog.addEventListener('close',()=>{generation++;release()});close.addEventListener('click',()=>dialog.close());apply.addEventListener('click',()=>{void submit()})
  async function submit(){
    if(disposed||busy||!dialog.open)return
    const reason=options.unavailable();if(reason){status.textContent=reason;return}
    const token=generation,target=format;busy=true;apply.disabled=true;release();status.textContent='正在生成独立 Word…'
    const active=()=>!disposed&&dialog.open&&token===generation
    try{
      const result=await options.convertOffice({format:'docx',requestId:crypto.randomUUID(),expectedSha256:options.sourceSha256})
      if(!active())return
      if(result.source?.sha256!==options.sourceSha256)throw Error('转换来源身份发生变化')
      wordLink(result)
      const bytes=await verifiedPdfTextDocx(result,options.sourceSha256,owner.baseURI,options.fetchFile??(url=>fetch(url,{credentials:'same-origin',redirect:'error'})))
      if(!active())return
      status.textContent='Word 已核验；正在使用文档渲染器导出…'
      const rendered=await(await import('./pdf-export-text-render')).renderPdfTextExport(bytes,target)
      if(!active())return
      blobUrl=URL.createObjectURL(new Blob([rendered.text],{type:target==='html'?'text/html;charset=utf-8':'text/markdown;charset=utf-8'}))
      const link=owner.createElement('a');link.href=blobUrl;link.download=target==='html'?'pdf-report.html':'pdf-report.md';link.textContent=target==='html'?'下载 HTML':'下载 Markdown';links.prepend(link)
      status.textContent='导出完成，仅供本次会话下载；验收未通过，需人工核对。'+[...result.validation.issues.map(issue=>issue.message??issue.code),...result.conversion?.warnings??[],...rendered.warnings].join('；')
    }catch(error){if(active())status.textContent=(error instanceof Error?error.message:String(error))+'；已生成的 Word 下载仍可使用。'}
    finally{busy=false;if(!disposed)apply.disabled=false}
  }
  return{open(value:PdfTextExportFormat){if(disposed||busy||dialog.open||options.unavailable())return;generation++;format=value;release();title.textContent='导出 '+(value==='html'?'HTML':'Markdown');dialog.setAttribute('aria-label',title.textContent);apply.textContent='生成 '+(value==='html'?'HTML':'Markdown');status.textContent='';dialog.showModal()},dispose(){if(disposed)return;disposed=true;generation++;release();dialog.remove()}}
}
