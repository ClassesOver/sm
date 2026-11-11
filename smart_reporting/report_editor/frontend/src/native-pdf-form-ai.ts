import {bindOfficeAssistantPanel} from './office-assistant-panel'
/** AI 仅填写明确授权的已有字段，候选须显式采纳到原生草稿。 */
import {createElement,Sparkles,Check,CircleStop,X} from 'lucide'
import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfFormField} from './pdf-operations'
import {mountNativeAIProgress,type NativeAIProgressListener} from './native-ai-progress'
export interface PDFFormAIProposal {summary:string;operations:NativeOperation[];changes:{fieldId:string;name:string;fieldKind:string;before:unknown;after:unknown}[];previewDigest:string;appliedOperationIndices:number[];skippedOperations:{operationIndex:number;reason:string}[]}
export interface PDFFormAIJob {editId:string;status:'running'|'succeeded'|'failed'|'cancelled';snapshotSha256:string;result?:{answer:string;proposal:PDFFormAIProposal;snapshotSha256?:string};error?:{message:string}}
export interface PDFFormAIClient {
 pdfFormAIStart(payload:{clientRequestId:string;expectedSha256:string;operations:NativeOperation[];selection:{fieldId:string}[];instruction:string},signal:AbortSignal):Promise<PDFFormAIJob>
 pdfFormAIStatus(id:string,signal:AbortSignal):Promise<PDFFormAIJob>
 pdfFormAIEvents?:NativeAIProgressListener
 pdfFormAIAccept(id:string,payload:{expectedSha256:string;operations:NativeOperation[];snapshotSha256:string},signal:AbortSignal):Promise<{operations:NativeOperation[];previewDigest:string}>
 pdfFormAICancel(clientRequestId:string):Promise<unknown>
}
export function bindNativePDFFormAI(root:HTMLElement,options:{api:PDFFormAIClient;draft:NativeDraft;fields:()=>PdfFormField[];view:{refresh():Promise<void>};canEdit():boolean;onDraftChange():void}){
 const panel=document.createElement('section');panel.className='native-ai native-ai-panel native-pdf-form-ai';panel.hidden=true;panel.setAttribute('aria-label','AI 填写 PDF 表单')
 const title=document.createElement('h3');title.textContent='AI 填写表单'
 const help=document.createElement('p');help.textContent='请明确勾选允许填写的已有字段。只提出填值建议，不创建字段、不签名；核对实际字段与 PDF 预览后采纳到草稿，仍需保存。'
 const fields=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='授权填写字段（默认不选）';fields.append(legend)
 const list=document.createElement('div');fields.append(list)
 const input=document.createElement('textarea');input.maxLength=2000;input.setAttribute('aria-label','AI 表单填写要求')
 const button=(id:string,label:string,icon:typeof Sparkles)=>{const b=document.createElement('button');b.type='button';b.dataset.pdfFormAi=id;b.append(createElement(icon,{'aria-hidden':'true',width:18,height:18}),document.createTextNode(label));return b}
 const start=button('start','生成填写建议',Sparkles),accept=button('accept','采纳到草稿',Check),cancel=button('cancel','取消建议',CircleStop),close=button('close','关闭助手',X)
 const status=document.createElement('p');status.setAttribute('role','status')
 const output=document.createElement('p'),details=document.createElement('div');details.className='native-ai-evidence'
 panel.append(title,help,fields,input,start,accept,cancel,close,status,output,details);root.append(panel)
 const panelView=bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,onClose:()=>stop()})
 const progress=mountNativeAIProgress(panel)
 let disposed=false,busy=false,generation=0,request:string|undefined,controller:AbortController|undefined,job:PDFFormAIJob|undefined,base:NativeOperation[]=[],snapshot=''
 const selected=new Set<string>(),editable=()=>!disposed&&!options.draft.closed&&!options.draft.saving&&options.canEdit()
 const available=()=>options.fields().filter(field=>field.editable&&['text','checkbox','radio','choice'].includes(field.kind))
 const value=(field:PdfFormField)=>{const pending=options.draft.operations.findLast(op=>op.kind==='setFormValue'&&op.fieldId===field.fieldId);return pending?(field.kind==='checkbox'?pending.checked:pending.value):field.value}
 const text=(v:unknown)=>typeof v==='boolean'?(v?'已勾选':'未勾选'):v==null?'未填写':String(v)
 function capture(){const known=available();if(!selected.size||[...selected].some(id=>!known.some(f=>f.fieldId===id)))throw new Error('请选择有效字段；失效选区不会扩大为全部表单');return JSON.stringify({instruction:input.value.trim(),operations:options.draft.operations,fields:known.filter(f=>selected.has(f.fieldId)).map(f=>({...f,currentValue:value(f)}))})}
 function update(){start.disabled=busy||!editable()||!selected.size||!input.value.trim();accept.disabled=busy||!editable()||job?.status!=='succeeded'||!job.result;cancel.disabled=!request;fields.disabled=busy||!editable()}
 function stop(message='建议已取消') {const id=request,turn=++generation;request=undefined;controller?.abort();progress.reset();busy=false;job=undefined;output.textContent='';details.replaceChildren();status.textContent=message;update();if(id)void options.api.pdfFormAICancel(id).catch(error=>{if(turn===generation&&!disposed)status.textContent=error instanceof Error?error.message:'取消失败'})}
 function renderFields(){list.replaceChildren();for(const field of available()){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.dataset.pdfFormAiField=field.fieldId;check.checked=selected.has(field.fieldId);check.onchange=()=>{if(request)stop('授权字段已变化，请重新生成建议');if(check.checked)selected.add(field.fieldId);else selected.delete(field.fieldId);update()};label.append(check,document.createTextNode(field.name+'：'+text(value(field))));list.append(label)}}
 async function run(){
  if(busy||!editable()||!input.value.trim())return
  if(request)stop('开始新的填写建议')
  try{snapshot=capture()}catch(error){status.textContent=(error as Error).message;return}
  const turn=++generation;base=structuredClone(options.draft.operations);const selection=[...selected].map(fieldId=>({fieldId}));request=crypto.randomUUID();controller=new AbortController();const signal=controller.signal;busy=true;job=undefined;output.textContent='';details.replaceChildren();status.textContent='正在读取授权字段并核验填写建议';update()
  try{
   let result=await options.api.pdfFormAIStart({clientRequestId:request,expectedSha256:options.draft.identity.sourceSha256,operations:base,selection,instruction:input.value.trim()},signal)
   if(turn!==generation||disposed)return
   progress.start(options.api.pdfFormAIEvents,result.editId,signal,()=>turn===generation&&editable())
   while(turn===generation&&!disposed&&result.status==='running')result=await options.api.pdfFormAIStatus(result.editId,signal)
   if(turn!==generation||disposed)return
   if(!editable()||capture()!==snapshot)throw new Error('草稿或授权字段已变化，请重新生成建议')
   if(result.status!=='succeeded'||!result.result){status.textContent=result.error?.message??'未返回可采纳建议';return}
   if(result.result.proposal.changes.some(change=>!selected.has(change.fieldId)))throw new Error('候选包含未授权字段，请重新生成建议')
   job=result;output.textContent=result.result.answer
   const p=result.result.proposal,summary=document.createElement('p');summary.textContent=p.summary+'；实际预览执行 '+p.appliedOperationIndices.length+' 项，跳过 '+p.skippedOperations.length+' 项';details.append(summary)
   for(const change of p.changes){const line=document.createElement('p');line.textContent=change.name+'（'+change.fieldKind+'）：'+text(change.before)+' → '+text(change.after);details.append(line)}
   for(const skipped of p.skippedOperations){const line=document.createElement('p');line.textContent='第'+(skipped.operationIndex+1)+'项未执行：'+skipped.reason;details.append(line)}
   status.textContent='填写建议已核验，请核对实际字段值后采纳'
  }catch(error){if(turn===generation&&!disposed){job=undefined;status.textContent=error instanceof Error?error.message:'填写建议失败'}}finally{if(turn===generation&&!disposed){busy=false;progress.stop();update()}}
 }
 async function apply(){
  if(busy||!editable()||job?.status!=='succeeded'||!job.result)return
  try{if(capture()!==snapshot)throw new Error('草稿或授权字段已变化，请重新生成建议')}catch(error){job=undefined;status.textContent=(error as Error).message;update();return}
  const turn=generation,candidate=job;busy=true;controller=new AbortController();update();let staged=false
  try{
   const result=await options.api.pdfFormAIAccept(candidate.editId,{expectedSha256:options.draft.identity.sourceSha256,operations:structuredClone(base),snapshotSha256:candidate.snapshotSha256??candidate.result?.snapshotSha256??''},controller.signal)
   if(turn!==generation||disposed)return
   if(!editable()||capture()!==snapshot)throw new Error('草稿或授权字段已变化，请重新生成建议')
   options.draft.setOperations(result.operations);staged=true;options.onDraftChange();job=undefined;request=undefined;await options.view.refresh()
   if(turn!==generation||disposed)return
   renderFields();status.textContent='填写建议已进入草稿，请核对实际 PDF 预览并保存。'
  }catch(error){if(turn===generation&&!disposed)status.textContent=(staged?'建议已进入草稿，但预览刷新失败：':'')+(error instanceof Error?error.message:'采纳失败')}finally{if(turn===generation&&!disposed){busy=false;update()}}
 }
 start.onclick=()=>{void run()};accept.onclick=()=>{void apply()};cancel.onclick=()=>stop();close.onclick=()=>{stop();panel.hidden=true};input.oninput=()=>{if(request)stop('填写要求已变化，请重新生成建议');update()};update()
 return{open(fieldId?:string){if(disposed)return;panelView.beforeOpen();if(request)stop();if(fieldId){selected.clear();if(available().some(f=>f.fieldId===fieldId))selected.add(fieldId);else status.textContent='当前字段不可填写'}renderFields();panel.hidden=false;update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})},update,dispose(){if(disposed)return;panelView.dispose();stop();disposed=true;panel.remove()}}
}
