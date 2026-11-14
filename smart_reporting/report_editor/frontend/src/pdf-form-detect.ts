import type {PDFDocumentProxy} from 'pdfjs-dist'
import {collectDetectInput,detectFormFields} from './vendor/genoffice-pdf/renderer/form-detect'
import {stagePdfFormCreation,type PdfFormCreateModel,type PdfFormCreation} from './pdf-form-create'
import type {NativeDraft,NativeOperation} from './native-draft'
import {showPdfObjectDialog} from './pdf-object-dialog'

export interface PdfDetectedFormCandidate extends PdfFormCreation {sourceSha256:string}
export function stagePdfDetectedForm(model:PdfFormCreateModel,operations:NativeOperation[],candidate:PdfDetectedFormCandidate){
 const {sourceSha256,...input}=candidate
 if(sourceSha256!==model.sourceSha256)throw Error('检测来源已变化，请重新检测')
 return stagePdfFormCreation(model,operations,input)
}

/** 固定源算法只生成候选；当前保存契约仍是一次确认一个字段。 */
export async function collectPdfFormCandidates(model:PdfFormCreateModel,document:PDFDocumentProxy,assertCurrent:()=>void){
 const candidates:PdfDetectedFormCandidate[]=[],skipped:string[]=[],taken=new Set((model.formDesignWidgets??[]).map(w=>w.fieldName))
 if(document.numPages!==model.pages.length||new Set(model.pages.map(p=>p.pageId)).size!==model.pages.length)throw Error('来源页身份已变化，请重新检测')
 let count=0
 for(let index=0;index<model.pages.length;index++){
  assertCurrent()
  const identity=model.pages[index],pageIndex=identity.index??index
  if(pageIndex!==index)throw Error('来源页顺序已变化，请重新检测')
  const page=await document.getPage(pageIndex+1);assertCurrent()
  const b=identity.cropBox,box=[b.x,b.y,b.x+b.width,b.y+b.height]
  if(page.pageNumber!==pageIndex+1||page.userUnit!==1||page.rotate!==(identity.rotation??0)||page.view.length!==4||page.view.some((v,i)=>Math.abs(v-box[i])>0.01))throw Error('来源页面坐标已变化，请重新检测')
  const input=await collectDetectInput(page);assertCurrent()
  const fields=detectFormFields({pageIndex,pageBox:box as [number,number,number,number],...input,occupied:(model.formDesignWidgets??[]).filter(w=>w.pageIndex===pageIndex).map(w=>w.rect),taken})
  for(const field of fields.slice(0,300-count)){
   count++;taken.add(field.name)
   if(field.kind!=='text'&&field.kind!=='checkbox'){skipped.push(`${field.name}：${field.kind==='signature'?'签名字段不支持':'该字段类型暂不支持'}`);continue}
   const candidate:PdfDetectedFormCandidate={sourceSha256:model.sourceSha256,pageId:identity.pageId,fieldName:field.name,fieldKind:field.dateFormat?'date':field.kind,rect:field.rect,required:false,...(field.dateFormat?{dateFormat:field.dateFormat as PdfFormCreation['dateFormat']}:{})}
   try{stagePdfDetectedForm(model,[],candidate);candidates.push(candidate)}catch(error){skipped.push(`${field.name}：${error instanceof Error?error.message:String(error)}`)}
  }
  if(count>=300)break
 }
 assertCurrent();return {candidates,skipped}
}

export function bindPdfFormDetect(options:{root:HTMLElement;draft:NativeDraft;model:()=>PdfFormCreateModel;sourceDocument:()=>PDFDocumentProxy|undefined;activePageId:()=>string;unavailable:()=>string|null;refresh:()=>Promise<void>}){
 const owner=options.root.ownerDocument
 let disposed=false,dialog:HTMLDialogElement|undefined,invalidate:(()=>void)|undefined
 const key=()=>JSON.stringify([options.draft.identity,options.model(),options.activePageId(),options.draft.operations,options.draft.canUndo,options.draft.canRedo])
 function unavailable(){return options.unavailable()||(options.draft.closed||options.draft.saving?'当前修订无法检测字段':options.draft.operations.length?'表单字段设计须单独保存，请先保存或撤销其他修改':options.model().sourceSha256!==options.draft.identity.sourceSha256?'来源身份已变化':options.model().capabilities?.createFormField!==true?options.model().capabilities?.createFormFieldReason||'当前来源不能安全创建字段':null)}
 return {open(){
  if(disposed||dialog?.open||unavailable())return
  const source=options.sourceDocument();if(!source)return
  const snapshot=key(),model=structuredClone(options.model()),view=owner.createElement('dialog'),body=owner.createElement('div'),hint=owner.createElement('p'),status=owner.createElement('p'),choices=owner.createElement('fieldset'),legend=owner.createElement('legend'),actions=owner.createElement('footer'),close=owner.createElement('button'),apply=owner.createElement('button')
  dialog=view;view.className='pdf-layout-dialog pdf-extract-dialog pdf-form-detect-dialog';view.setAttribute('aria-label','自动检测表单字段');body.className='pdf-extract-body';status.setAttribute('role','status');legend.textContent='选择一个候选字段';choices.append(legend)
  hint.textContent='使用固定源的页面文字、下划线与线框检测，不使用 AI 或 OCR。请核对名称、类型、来源页与坐标；一次只加入一个字段，生成实际预览并保存后可重新检测。签名候选会跳过。';status.textContent='正在检测来源页面…'
  close.type=apply.type='button';close.textContent='取消';apply.textContent='将所选字段加入草稿';apply.dataset.pdfFormDetectApply='';apply.disabled=true;actions.className='pdf-layout-actions';actions.append(close,apply);body.append(hint,status,choices);view.append(body,actions);options.root.append(view)
  let stale=false,selected:PdfDetectedFormCandidate|undefined,finished=false
  const current=()=>!disposed&&!stale&&!finished&&dialog===view&&view.open&&source===options.sourceDocument()&&snapshot===key()&&!unavailable()
  const reject=()=>{stale=true;status.textContent='来源、页面或草稿已变化，请关闭后重新检测';choices.disabled=true;apply.disabled=true}
  const assertCurrent=()=>{if(!current())throw Error('来源、页面或草稿已变化，请重新检测')}
  invalidate=()=>{if(!finished&&!current())reject()}
  close.addEventListener('click',()=>view.close())
  view.addEventListener('close',()=>{stale=true;if(dialog===view){dialog=undefined;invalidate=undefined}view.remove()},{once:true})
  apply.addEventListener('click',()=>{void (async()=>{
   let staged=false
   try{assertCurrent();if(!selected)return;options.draft.setOperations(stagePdfDetectedForm(options.model(),options.draft.operations,selected));staged=true;finished=true;choices.disabled=apply.disabled=true;await options.refresh();if(!disposed&&view.open)view.close()}
   catch(error){if(!disposed&&view.isConnected){if(!staged&&!current())reject();else status.textContent=(staged?'字段已加入草稿，草稿已保留；':'')+(error instanceof Error?error.message:String(error))}}
  })()})
  showPdfObjectDialog(view,close)
  void collectPdfFormCandidates(model,source,assertCurrent).then(result=>{
   assertCurrent();status.textContent=`检测到 ${result.candidates.length} 个可用候选（每次最多扫描 300 项）。${result.skipped.length?'跳过：'+result.skipped.join('；'):''}${result.candidates.length?'请选择一个字段加入草稿。':'没有发现可创建字段；扫描件没有可用文字或线框时不会进行 OCR。'}`
   result.candidates.forEach((candidate,index)=>{
    const label=owner.createElement('label'),radio=owner.createElement('input');radio.type='radio';radio.name='pdf-form-detect-candidate';radio.value=String(index)
    const page=model.pages.findIndex(p=>p.pageId===candidate.pageId),kind={text:'文本',checkbox:'复选框',date:'日期'}[candidate.fieldKind as 'text'|'checkbox'|'date']
    label.textContent=`${candidate.fieldName} · ${kind} · 第${page+1}页 · [${candidate.rect.join(', ')}] `;radio.setAttribute('aria-label',label.textContent);label.prepend(radio);choices.append(label)
    radio.addEventListener('change',()=>{if(!current()){reject();return}selected=candidate;apply.disabled=false})
   })
  }).catch(error=>{if(!disposed&&view.isConnected){if(!current())reject();else status.textContent=error instanceof Error?error.message:String(error)}})
 },update(){invalidate?.()},dispose(){disposed=true;invalidate=undefined;if(dialog?.open)dialog.close();dialog?.remove();dialog=undefined}}
}
