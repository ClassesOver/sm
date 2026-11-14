import {createElement} from 'react'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {getDocument} from 'pdfjs-dist/legacy/build/pdf.mjs'
import type {PDFDocumentLoadingTask,PDFDocumentProxy} from 'pdfjs-dist'
import {bytesSha256} from './source-validation'
import {ComparePanel} from './vendor/genoffice-pdf/renderer/ComparePanel'
import type {CompareResult,PageText} from './vendor/genoffice-pdf/renderer/compare-text'
import {createPdfComparison} from './pdf-compare-compute'
import './pdf-compare.css'

const strings:Record<string,string>={loading:'正在读取…',comparePick:'选择另一个 PDF',compareSwap:'交换新旧',compareIdentical:'两个文档的文本一致',compareDiffPages:'有 {count} 页存在文本差异',comparePage:'第 {page} 页',compareAdded:'+{count} 行',compareRemoved:'−{count} 行',compareTruncated:'页面过大，仅统计行数'}
const t=(key:string,args?:Record<string,string|number>)=>(strings[key]??key).replace(/\{(\w+)\}/g,(_,name:string)=>String(args?.[name]??''))
interface Source {document:PDFDocumentProxy;sha256:string;size:number;name:string;pages:{index:number;pageId:string}[]}
interface Identity {name:string;size:number;sha256:string}

/** Both sides use PDF.js from saved file bytes. The fixed source's LCS and panel stay unchanged. */
export function bindPdfCompare(options:{container:HTMLElement;source:()=>Source|undefined;unavailable:()=>string|null;navigate:(pageId:string)=>void}){
 const {container}=options,owner=container.ownerDocument
 const host=owner.createElement('div'),input=owner.createElement('input'),notice=owner.createElement('p'),identity=owner.createElement('p'),cancelButton=owner.createElement('button')
 input.type='file';input.accept='.pdf,application/pdf';input.hidden=true;input.setAttribute('aria-label','选择用于比较的第二份 PDF')
 notice.className='pdf-compare-notice';notice.setAttribute('role','status');notice.tabIndex=0
 identity.className='pdf-compare-identity';identity.dataset.pdfCompareIdentity='';identity.hidden=true
 cancelButton.type='button';cancelButton.textContent='取消比较';cancelButton.hidden=true
 container.append(host,input,notice,identity,cancelButton)
 const root=createRoot(host)
 let disposed=false,generation=0,busy=false,swapped=false,result:CompareResult|null=null,other:Identity|null=null
 let sides:{mine:PageText[];theirs:PageText[];source:Source}|null=null,loading:PDFDocumentLoadingTask|undefined,calculation:ReturnType<typeof createPdfComparison>|undefined
 const release=()=>{calculation?.cancel();calculation=undefined;const task=loading;loading=undefined;if(task)void task.destroy().catch(()=>{})}
 function draw(){
  if(disposed)return
  const focused=owner.activeElement instanceof HTMLElement&&host.contains(owner.activeElement)?owner.activeElement.className:null
  flushSync(()=>root.render(createElement(ComparePanel,{t,result,otherName:other?.name??null,busy,onPick:pick,onSwap:()=>{void swap()},onGoToPage:(pageNo:number)=>{
   const reason=options.unavailable(),source=options.source()
   if(reason||!sides||source?.document!==sides.source.document){notice.textContent=reason??'来源文档已变化，请重新比较';return}
   const page=source.pages.find(page=>page.index===pageNo-1)
   if(page)options.navigate(page.pageId)
   else notice.textContent='此页仅存在于第二份 PDF，当前文档没有可跳转的来源页'
  }})))
  const differing=result?.pages.filter(page=>page.addedCount>0||page.removedCount>0)??[]
  host.querySelectorAll<HTMLButtonElement>('.pdf-compare-row').forEach((button,index)=>{const pageIndex=differing[index].pageIndex,page=sides?.source.pages.find(page=>page.index===pageIndex);button.dataset.pageIndex=String(pageIndex);if(page)button.dataset.pageId=page.pageId;else{button.disabled=true;button.title='此页仅存在于第二份 PDF，当前文档没有可跳转的来源页'}})
  const swapButton=host.querySelector<HTMLButtonElement>('.pdf-compare-swap');if(swapButton)swapButton.disabled=busy
  container.setAttribute('aria-busy',String(busy));cancelButton.hidden=!busy
  identity.hidden=!other
  if(other){identity.dataset.sha256=other.sha256;identity.dataset.size=String(other.size);identity.textContent=`用户选择：${other.name} · ${other.size} 字节 · SHA256 ${other.sha256}`}
  if(focused)host.getElementsByClassName(focused)[0]?.scrollIntoView?.({block:'nearest'})
 }
 async function calculate(mine:PageText[],theirs:PageText[],reversed=swapped){calculation=createPdfComparison(reversed?theirs:mine,reversed?mine:theirs);return calculation.promise}
 async function swap(){
  if(disposed||busy||!sides)return
  const reason=options.unavailable();if(reason){notice.textContent=reason;return}
  const token=++generation,current=sides,nextSwapped=!swapped
  busy=true;draw()
  try{const next=await calculate(current.mine,current.theirs,nextSwapped);if(disposed||token!==generation)return;swapped=nextSwapped;result=next}
  catch(error){if(!disposed&&token===generation)notice.textContent=`交换失败：${error instanceof Error?error.message:String(error)}`}
  finally{if(!disposed&&token===generation){release();busy=false;draw()}}
 }
 function pick(){
  const reason=options.unavailable()
  if(reason){notice.textContent=reason;return}
  if(disposed||busy)return
  input.value='';input.click()
 }
 async function extract(document:PDFDocumentProxy,stale:()=>boolean):Promise<PageText[]>{
  const pages:PageText[]=[]
  for(let index=0;index<document.numPages;index++){
   if(stale())return[]
   const content=await(await document.getPage(index+1)).getTextContent()
   if(stale())return[]
   let text=''
   for(const item of content.items)if('str'in item)text+=item.str+(item.hasEOL?'\n':' ')
   pages.push({pageIndex:index,text})
  }
  return pages
 }
 async function run(){
  const file=input.files?.[0];input.value=''
  if(!file||disposed)return
  const reason=options.unavailable(),source=options.source()
  if(reason||!source){notice.textContent=reason??'请先打开来源 PDF';return}
  cancel(false);const token=++generation
  const stale=()=>disposed||token!==generation||options.source()?.document!==source.document||options.unavailable()!==null
  busy=true;notice.textContent='正在读取用户选择的 PDF；只比较已保存的来源文本，不上传第二份文件。';draw()
  try{
   const bytes=new Uint8Array(await file.arrayBuffer()),sha256=await bytesSha256(bytes)
   if(stale())return
   if(bytes.byteLength!==file.size)throw Error('第二份 PDF 的字节数与文件身份不一致')
   loading=getDocument({data:bytes,cMapUrl:'/reports/v1/editor/assets/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/reports/v1/editor/assets/pdfjs/standard_fonts/',wasmUrl:'/reports/v1/editor/assets/pdfjs/wasm/',enableXfa:false})
   const theirsDocument=await loading.promise
   if(stale())return
   const theirs=await extract(theirsDocument,stale),mine=await extract(source.document,stale)
   if(stale())return
   const next=await calculate(mine,theirs)
   if(stale())return
   sides={mine,theirs,source};other={name:file.name,size:file.size,sha256};result=next
   notice.textContent=`按原始页序比较已保存文本（当前 ${mine.length} 页，第二份 ${theirs.length} 页）；不比较图像、排版或未保存修改。`
   if([...mine,...theirs].some(page=>!page.text.trim()))notice.textContent+=' 部分页面无可提取文本（可能为空白页或扫描件），无法判断视觉内容是否一致；未执行 OCR。'
   if(theirs.length>mine.length)notice.textContent+=' 第二份独有页面仅列出差异，当前文档无对应来源页。'
  }catch(error){if(!stale()){result=null;sides=null;other=null;notice.textContent=error instanceof Error&&error.name==='PasswordException'?'第二份 PDF 需要密码；未执行比较，请选择可读取的 PDF。':`比较失败：${error instanceof Error?error.message:String(error)}`}}
  finally{if(token===generation){release();busy=false;if(stale()){result=null;sides=null;other=null;notice.textContent=options.unavailable()??'来源文档已变化，请重新比较'}draw()}}
 }
 function cancel(message=true){generation++;release();busy=false;if(message)notice.textContent='已取消本次比较；文件和草稿未改变';draw()}
 const onChange=()=>{void run()},onCancel=()=>{if(!disposed)notice.textContent='已取消文件选择；原比较结果保留'},onKey=(event:KeyboardEvent)=>{if(event.key==='Escape'&&busy){event.preventDefault();cancel()}}
 input.addEventListener('change',onChange);input.addEventListener('cancel',onCancel);cancelButton.addEventListener('click',()=>cancel());container.addEventListener('keydown',onKey)
 container.addEventListener('focusin',event=>(event.target as HTMLElement).scrollIntoView?.({block:'nearest'}))
 draw()
 return{cancel,focus(){host.querySelector<HTMLButtonElement>('.pdf-compare-pick')?.focus({preventScroll:true})},sync(){if((busy||sides)&&options.unavailable()){cancel(false);result=null;sides=null;other=null;notice.textContent=options.unavailable();draw()}},dispose(){if(disposed)return;generation++;release();disposed=true;input.removeEventListener('change',onChange);input.removeEventListener('cancel',onCancel);container.removeEventListener('keydown',onKey);flushSync(()=>root.unmount());container.replaceChildren()}}
}
