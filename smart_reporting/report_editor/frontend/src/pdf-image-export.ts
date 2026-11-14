import { parsePdfExtractPages } from './pdf-extract-dialog'
export interface PdfImageExportRequest {expectedSha256:string;pages:number[];format:'png'|'jpeg';dpi:number}
export interface PdfImageExportResult {content:ArrayBuffer;sha256:string;size:number;sourceSha256:string;filename:string}
export function bindPdfImageExportDialog(options:{root:HTMLElement;sourceSha256:string;pageCount:()=>number;currentPage:()=>number;unavailable:()=>string|null;exportImages:(payload:PdfImageExportRequest)=>Promise<PdfImageExportResult>}){
  const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog';dialog.setAttribute('aria-label','导出 PDF 页面图片')
  const title=owner.createElement('h3');title.textContent='导出 PDF 页面图片'
  const hint=owner.createElement('p');hint.textContent='从已保存来源渲染 PNG/JPEG，以 ZIP 在本次会话直接下载；不是持久化下载链接。最多 50 页，单页 2000 万、总计 1 亿像素，输出不超过 64 MiB。'
  const pageLabel=owner.createElement('label');pageLabel.textContent='页码（例如 4,1-2）';const pages=owner.createElement('input');pages.setAttribute('aria-label','导出图片页码');pageLabel.append(pages)
  const formatLabel=owner.createElement('label');formatLabel.textContent='图片格式';const format=owner.createElement('select');format.setAttribute('aria-label','导出图片格式')
  for(const [value,text]of [['png','PNG'],['jpeg','JPEG']]){const item=owner.createElement('option');item.value=value!;item.textContent=text!;format.append(item)}formatLabel.append(format)
  const dpiLabel=owner.createElement('label');dpiLabel.textContent='分辨率 DPI';const dpi=owner.createElement('input');dpi.type='number';dpi.min='72';dpi.max='216';dpi.step='1';dpi.value='144';dpi.setAttribute('aria-label','导出图片 DPI');dpiLabel.append(dpi)
  const apply=owner.createElement('button');apply.type='button';apply.textContent='生成图片 ZIP';apply.dataset.pdfImageExportApply=''
  const close=owner.createElement('button');close.type='button';close.textContent='关闭'
  const status=owner.createElement('p');status.setAttribute('role','status');const delivery=owner.createElement('div')
  const actions=owner.createElement('div');actions.className='pdf-layout-actions';actions.append(close,apply)
  delivery.className='pdf-layout-delivery'
  dialog.append(title,hint,pageLabel,formatLabel,dpiLabel,status,delivery,actions);options.root.append(dialog)
  let busy=false,disposed=false,generation=0,url:string|undefined
  dialog.addEventListener('keydown',event=>{if(busy&&event.key==='Tab'){event.preventDefault();close.focus()}})
  function release(){if(url){URL.revokeObjectURL(url);url=undefined}delivery.replaceChildren()}
  dialog.addEventListener('close',()=>{generation++;release()});close.addEventListener('click',()=>dialog.close())
  apply.addEventListener('click',()=>{void submit()})
  async function submit(){
    if(disposed||busy||!dialog.open)return
    const blocked=options.unavailable();if(blocked){status.textContent=blocked;return}
    let selected:number[],resolution:number
    try{selected=parsePdfExtractPages(pages.value,options.pageCount());resolution=Number(dpi.value);if(selected.length>50||!Number.isSafeInteger(resolution)||resolution<72||resolution>216||!['png','jpeg'].includes(format.value))throw Error('图片页数、格式或 DPI 无效')}catch(error){status.textContent=error instanceof Error?error.message:String(error);return}
    const token=generation;busy=true;apply.disabled=true;pages.disabled=format.disabled=dpi.disabled=true;release();status.textContent='正在渲染页面图片…'
    try{
      const result=await options.exportImages({expectedSha256:options.sourceSha256,pages:selected,format:format.value as 'png'|'jpeg',dpi:resolution})
      if(disposed||!dialog.open||generation!==token)return
      const bytes=new Uint8Array(result.content)
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',result.content)),value=>value.toString(16).padStart(2,'0')).join('')
      if(disposed||!dialog.open||generation!==token)return
      if(result.sourceSha256!==options.sourceSha256||bytes.length!==result.size||bytes.length>64*1024*1024||digest!==result.sha256||bytes[0]!==80||bytes[1]!==75||bytes[2]!==3||bytes[3]!==4)throw Error('图片 ZIP 文件身份校验失败，请重新导出')
      url=URL.createObjectURL(new Blob([result.content],{type:'application/zip'}));const link=owner.createElement('a');link.href=url;link.download=/^[a-zA-Z0-9_.-]+\.zip$/.test(result.filename)?result.filename:'pdf-pages.zip';link.textContent='下载图片 ZIP';delivery.append(link)
      status.textContent='图片 ZIP 已核验身份；仅供本次会话直接下载，关闭窗口后链接失效。'
    }catch(error){if(!disposed&&dialog.open&&generation===token)status.textContent=error instanceof Error?error.message:String(error)}
    finally{busy=false;if(!disposed&&dialog.open&&generation===token){apply.disabled=false;pages.disabled=format.disabled=dpi.disabled=false}}
  }
  return {open(preferred:'png'|'jpeg'='png'){if(disposed||busy||dialog.open||options.unavailable())return;generation++;release();format.value=preferred;pages.value=String(options.currentPage());status.textContent='';apply.disabled=false;pages.disabled=format.disabled=dpi.disabled=false;dialog.showModal()},dispose(){if(disposed)return;disposed=true;generation++;release();dialog.remove()}}
}
