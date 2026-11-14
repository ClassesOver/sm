import type {NativeSaveResponse} from './native-api'
export type PdfConvertOfficeFormat='pptx'|'docx'|'xlsx'
export interface PdfConvertOfficeRequest {requestId:string;expectedSha256:string;format:PdfConvertOfficeFormat}
export interface PdfConvertOfficeResult extends NativeSaveResponse {conversion?:{warnings:string[]}}
export function bindPdfConvertOfficeDialog(options:{root:HTMLElement;sourceSha256:string;unavailable:()=>string|null;submit:(payload:PdfConvertOfficeRequest)=>Promise<PdfConvertOfficeResult>}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog'
 const labels={pptx:'PowerPoint',docx:'Word',xlsx:'Excel'},artifactKeys={pptx:'pptx',docx:'word',xlsx:'xlsx'} as const
 const title=owner.createElement('h3')
 const hint=owner.createElement('p');hint.textContent='使用固定来源的本地转换引擎创建独立文档，原 PDF 保留。文字、表格与版式可能变化，需人工核对；不执行 OCR。'
 const apply=owner.createElement('button');apply.type='button';apply.textContent='生成 PPTX';apply.dataset.pdfConvertOfficeApply=''
 const close=owner.createElement('button');close.type='button';close.textContent='关闭'
 const status=owner.createElement('p');status.setAttribute('role','status');const links=owner.createElement('div')
 const actions=owner.createElement('div');actions.className='pdf-layout-actions';actions.append(close,apply)
 links.className='pdf-layout-delivery'
 dialog.append(title,hint,status,links,actions);options.root.append(dialog)
 let disposed=false,busy=false,generation=0,format:PdfConvertOfficeFormat='pptx'
 dialog.addEventListener('keydown',event=>{if(busy&&event.key==='Tab'){event.preventDefault();close.focus()}})
 const cached=new Map<PdfConvertOfficeFormat,PdfConvertOfficeResult>()
 function link(href:string|undefined,label:string){
  if(!href)return
  try{const url=new URL(href,owner.baseURI);if(!['http:','https:'].includes(url.protocol)||url.origin!==new URL(owner.baseURI).origin)return}catch{return}
  const anchor=owner.createElement('a');anchor.href=href;anchor.textContent=label;anchor.rel='noopener';links.append(anchor)
 }
 function show(result:PdfConvertOfficeResult){
  status.textContent=format.toUpperCase()+' 已生成；'+(result.validation.ok?'验收通过':'验收未通过')+'：'+[...result.validation.issues.map(issue=>issue.message||issue.code),...result.conversion?.warnings??[]].join('；')
  links.replaceChildren();link(result.artifacts[artifactKeys[format]]?.downloadUrl,'下载转换后的 '+format.toUpperCase());link(result.editor?.openUrl,'打开独立'+labels[format]+'文档')
 }
 apply.addEventListener('click',()=>{void submit()});close.addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>generation++)
 async function submit(){
  if(disposed||busy||!dialog.open)return
  const reason=options.unavailable();if(reason){status.textContent=reason;return}
  const token=generation,requestedFormat=format;busy=true;apply.disabled=true;links.replaceChildren();status.textContent='正在本地转换 PDF…'
  try{const result=await options.submit({requestId:crypto.randomUUID(),expectedSha256:options.sourceSha256,format:requestedFormat});cached.set(requestedFormat,result);if(!disposed&&dialog.open&&token===generation)show(result)}
  catch(error){if(!disposed&&dialog.open&&token===generation)status.textContent=error instanceof Error?error.message:String(error)}
  finally{busy=false;if(!disposed)apply.disabled=false}
 }
 return {open(value:PdfConvertOfficeFormat='pptx'){if(disposed||busy||dialog.open||options.unavailable())return;generation++;format=value;title.textContent='转换 PDF 为 '+labels[format];dialog.setAttribute('aria-label','转换 PDF 为'+(format==='pptx'?'演示文稿':labels[format]));apply.textContent='生成 '+format.toUpperCase();const previous=cached.get(format);if(previous)show(previous);else{status.textContent='';links.replaceChildren()}dialog.showModal()},dispose(){if(disposed)return;disposed=true;generation++;cached.clear();dialog.remove()}}
}
