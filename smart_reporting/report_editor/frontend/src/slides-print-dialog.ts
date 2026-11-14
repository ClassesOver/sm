import {buildPrintDocumentHtml,currentRangeIndices,parsePrintRange,printPageCount,type PrintLayout,type PrintOrientation} from './vendor/genoffice/shared/print-html'
import {showSlidesSettingsDialog} from './slides-settings-dialog'
import './slides-print.css'

export interface SlidesPrintSnapshot {ratio:number;current:number;slides:{src:string;notes:string;hidden:boolean}[]}
/** 当前草稿冻结快照；复用固定源页面组装，打印设备设置交由浏览器系统对话框。 */
export function openSlidesPrintDialog(root:HTMLElement,options:{load:(signal:AbortSignal)=>Promise<SlidesPrintSnapshot>;isCurrent:()=>boolean}){
 const doc=root.ownerDocument,dialog=doc.createElement('dialog');dialog.className='slides-print-dialog';dialog.setAttribute('aria-label','打印幻灯片')
 const title=doc.createElement('h3');title.textContent='打印幻灯片'
 const preview=doc.createElement('iframe');preview.title='幻灯片打印预览';preview.setAttribute('sandbox','allow-same-origin')
 const fields=doc.createElement('section');fields.className='slides-print-options'
 function select(label:string,choices:[string,string][]){const wrap=doc.createElement('label');wrap.textContent=label;const input=doc.createElement('select');input.setAttribute('aria-label',label);for(const [value,text]of choices){const option=doc.createElement('option');option.value=value;option.textContent=text;input.append(option)}wrap.append(input);fields.append(wrap);input.addEventListener('change',update);return input}
 function check(label:string){const wrap=doc.createElement('label'),input=doc.createElement('input');input.type='checkbox';input.setAttribute('aria-label',label);wrap.append(input,doc.createTextNode(label));fields.append(wrap);input.addEventListener('change',update);return input}
 const rangeMode=select('打印范围',[['all','全部幻灯片'],['current','当前幻灯片'],['custom','指定页码']])
 const rangeLabel=doc.createElement('label');rangeLabel.textContent='页码（例如 1,3-5）';const range=doc.createElement('input');range.type='text';range.setAttribute('aria-label','打印页码');rangeLabel.append(range);fields.append(rangeLabel);range.addEventListener('input',update)
 const layout=select('打印布局',[['full','整页幻灯片'],['handout2','讲义：每页 2 张'],['handout3','讲义：每页 3 张（带笔记线）'],['handout6','讲义：每页 6 张'],['notes','备注页']])
 const orientation=select('纸张方向',[['portrait','纵向'],['landscape','横向']]),frame=check('幻灯片加框'),hidden=check('打印隐藏幻灯片')
 const help=doc.createElement('p');help.textContent='打印当前草稿的静态快照。打印机、份数与双面设置请在系统打印对话框中选择。';fields.append(help)
 const status=doc.createElement('p');status.setAttribute('role','status');status.textContent='正在读取当前草稿打印快照…'
 const error=doc.createElement('p');error.setAttribute('role','alert')
 const cancel=doc.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.addEventListener('click',()=>dialog.close())
 const print=doc.createElement('button');print.type='button';print.textContent='打印';print.dataset.slidesPrintConfirm='';print.disabled=true
 const actions=doc.createElement('footer');actions.append(cancel,print);fields.append(status,error,actions);const body=doc.createElement('div');body.className='slides-print-body';body.append(preview,fields);dialog.append(title,body);root.append(dialog)
 const controller=new AbortController();let disposed=false,snapshot:SlidesPrintSnapshot|undefined,job:HTMLIFrameElement|undefined,jobController:AbortController|undefined,printing=false
 function zoomPreview(){const body=preview.contentDocument?.body,page=body?.querySelector<HTMLElement>('.page');if(disposed||!body||!page)return;body.style.zoom='';const width=page.getBoundingClientRect().width;if(width>0&&preview.clientWidth>44)body.style.zoom=String(Math.min((preview.clientWidth-44)/width,1))}
 preview.addEventListener('load',zoomPreview);const observer=typeof ResizeObserver==='undefined'?undefined:new ResizeObserver(zoomPreview);observer?.observe(preview);window.addEventListener('resize',zoomPreview)
 const selected=()=>{if(!snapshot)return [];const indices=rangeMode.value==='current'?currentRangeIndices(snapshot.current,snapshot.slides.length):rangeMode.value==='custom'?parsePrintRange(range.value,snapshot.slides.length):snapshot.slides.map((_,i)=>i);return indices?.filter(index=>hidden.checked||!snapshot!.slides[index]!.hidden)??null}
 const html=(indices:number[],isPreview:boolean)=>buildPrintDocumentHtml({srcs:indices.map(index=>snapshot!.slides[index]!.src),notes:indices.map(index=>snapshot!.slides[index]!.notes),ratio:snapshot!.ratio,layout:layout.value as PrintLayout,orientation:orientation.value as PrintOrientation,frame:frame.checked,preview:isPreview})
 function update(){
  if(disposed)return
  range.disabled=rangeMode.value!=='custom';orientation.disabled=layout.value==='full';frame.disabled=layout.value!=='full'
  const indices=selected();print.disabled=!snapshot||!indices?.length||printing
  if(!snapshot)return
  error.textContent=indices===null?'页码格式无效或超出范围':!indices.length?'没有可打印的幻灯片，请调整范围或隐藏页选项':''
  status.textContent=indices?.length?`${indices.length} 张幻灯片 · ${printPageCount(indices.length,layout.value as PrintLayout)} 页`:'0 页'
  preview.srcdoc=indices?.length?html(indices,true):''
 }
 const clearJob=()=>{job?.remove();job=undefined;jobController?.abort();jobController=undefined;printing=false;if(!disposed)print.disabled=!selected()?.length}
 print.addEventListener('click',()=>{
  if(disposed||printing||!snapshot)return
  if(!options.isCurrent()){error.textContent='文档或草稿已变化，请关闭并重新打开打印预览';return}
  const indices=selected();if(!indices?.length){update();return}
  clearJob();const jobAbort=new AbortController();jobController=jobAbort;printing=true;print.disabled=true;error.textContent=''
  const current=doc.createElement('iframe');current.title='系统打印内容';current.dataset.slidesPrintJob='';current.className='slides-print-job';current.setAttribute('sandbox','allow-same-origin allow-modals');job=current
  current.addEventListener('load',async()=>{
   if(disposed||job!==current)return
   try{
    const printDoc=current.contentDocument,win=current.contentWindow;if(!printDoc||!win)throw Error('无法读取打印页面')
    await Promise.all([...printDoc.images].map(image=>image.complete?image.naturalWidth?Promise.resolve():Promise.reject(Error('打印图片无法读取')):new Promise<void>((resolve,reject)=>{
     const cleanup=()=>{image.removeEventListener('load',loaded);image.removeEventListener('error',failed);jobAbort.signal.removeEventListener('abort',aborted)}
     const loaded=()=>{cleanup();resolve()},failed=()=>{cleanup();reject(Error('打印图片无法读取'))},aborted=()=>{cleanup();reject(Error('打印已取消'))}
     image.addEventListener('load',loaded,{once:true});image.addEventListener('error',failed,{once:true});jobAbort.signal.addEventListener('abort',aborted,{once:true})
    })))
    if(disposed||job!==current)return
    if(!options.isCurrent())throw Error('文档或草稿已变化，请重新打开打印预览')
    win.addEventListener('afterprint',()=>{if(job===current)clearJob()},{once:true});win.focus();win.print();printing=false;print.disabled=false
   }catch(cause){if(disposed||job!==current)return;error.textContent=cause instanceof Error?cause.message:'打印失败';clearJob()}
  },{once:true})
  current.srcdoc=html(indices,false);dialog.append(current)
 })
 function dispose(){if(disposed)return;disposed=true;controller.abort();clearJob();if(dialog.open)dialog.close();else dialog.remove()}
 dialog.addEventListener('close',()=>{observer?.disconnect();preview.removeEventListener('load',zoomPreview);window.removeEventListener('resize',zoomPreview);if(!disposed){disposed=true;controller.abort();clearJob()}},{once:true});showSlidesSettingsDialog(dialog)
 void options.load(controller.signal).then(value=>{
  if(disposed)return
  if(!options.isCurrent())throw Error('文档或草稿已变化，请重新打开打印预览')
  if(!value.slides.length||value.slides.some(slide=>!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(slide.src)))throw Error('打印快照未生成有效图片')
  snapshot=value;update()
 }).catch(cause=>{if(!disposed){status.textContent='';error.textContent=cause instanceof Error?cause.message:'打印快照读取失败'}})
 update();return {dispose}
}
