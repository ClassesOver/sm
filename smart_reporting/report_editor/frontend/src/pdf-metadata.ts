import './pdf-metadata.css'
import {metadataFields,validateMetadataOperation,type MetadataValues,type MetadataOperation} from '../../../reporting/pdf_engine/vendor/metadata/protocol'
import type {NativeDraft,NativeOperation} from './native-draft'
import {installFocusTrap} from './focus-trap'
export function validatePdfMetadata(operations:NativeOperation[],sourceSha256:string){
 const snapshots=operations.filter(op=>op.kind==='setMetadata');if(snapshots.length>1)throw Error('文档属性不能重复设置')
 for(const op of snapshots)validateMetadataOperation(op,sourceSha256)
}
export function metadataSnapshot(info:Record<string,unknown>,operations:NativeOperation[],sourceSha256:string):MetadataValues{
 validatePdfMetadata(operations,sourceSha256)
 const pending=operations.find(op=>op.kind==='setMetadata') as unknown as MetadataOperation|undefined
 return pending?structuredClone(pending.metadata):{title:String(info.Title??''),author:String(info.Author??''),subject:String(info.Subject??''),keywords:String(info.Keywords??'')}
}
export function stagePdfMetadata(operations:NativeOperation[],sourceSha256:string,metadata:MetadataValues,modifiedMs:number):NativeOperation[]{
 validatePdfMetadata(operations,sourceSha256);const op:MetadataOperation & NativeOperation={kind:'setMetadata',sourceSha256,modifiedMs,metadata:structuredClone(metadata)};validateMetadataOperation(op,sourceSha256)
 return [...operations.filter(op=>op.kind!=='setMetadata'),{...op}]
}
/** 源 PropertiesDialog：前四项为草稿字段，其余属性只读；确认后才进入历史。 */
export function bindPdfMetadata(options:{root:HTMLElement;draft:NativeDraft;info:Record<string,unknown>;fileName:string;fileSize:number;pageCount:()=>number;unavailable:()=>string|null;changed:()=>void;now?:()=>number}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog pdf-metadata-dialog';dialog.setAttribute('aria-label','文档属性')
 const title=owner.createElement('h3');title.textContent='文档属性';dialog.append(title)
 const fields=owner.createElement('div');fields.className='pdf-metadata-fields';const inputs={} as Record<typeof metadataFields[number],HTMLInputElement>
 for(const [index,key]of metadataFields.entries()){const label=owner.createElement('label');label.textContent=['标题','作者','主题','关键词'][index]!;const input=owner.createElement('input');input.type='text';input.maxLength=4096;input.setAttribute('aria-label','文档属性 '+label.textContent);label.append(input);fields.append(label);inputs[key]=input}dialog.append(fields)
 const list=owner.createElement('dl');list.className='pdf-metadata-readonly';dialog.append(list)
 const fmtDate=(raw:unknown)=>{const s=String(raw??''),m=/^D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?/.exec(s);return m?`${m[1]}-${m[2]}-${m[3]} ${m[4]??'00'}:${m[5]??'00'}`:s||'—'}
 const reason=owner.createElement('p');reason.setAttribute('role','status');dialog.append(reason)
 const error=owner.createElement('p');error.setAttribute('role','alert');dialog.append(error)
 const actions=owner.createElement('div');actions.className='pdf-layout-actions';const cancel=owner.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.dataset.metadataCancel='';const apply=owner.createElement('button');apply.type='button';apply.textContent='确定';apply.dataset.metadataApply='';actions.append(cancel,apply);dialog.append(actions);options.root.append(dialog)
 let disposed=false,snapshot='',returnFocus:HTMLElement|null=null
 cancel.addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>{const target=returnFocus?.isConnected&&!returnFocus.matches(':disabled')&&!returnFocus.closest('[hidden],[inert]')?returnFocus:options.root.querySelector<HTMLElement>('[data-pdf-ribbon-tab][aria-selected="true"]');target?.focus({preventScroll:true})});const trap=installFocusTrap(dialog)
 apply.addEventListener('click',()=>{if(disposed||!dialog.open)return;try{const blocked=options.unavailable();if(blocked)throw Error(blocked);if(snapshot!==JSON.stringify(options.draft.operations))throw Error('草稿已变化，请关闭后重新编辑文档属性');const values=Object.fromEntries(metadataFields.map(key=>[key,inputs[key].value])) as MetadataValues;options.draft.setOperations(stagePdfMetadata(options.draft.operations,options.draft.identity.sourceSha256,values,(options.now??Date.now)()));dialog.close();options.changed()}catch(cause){error.textContent=cause instanceof Error?cause.message:String(cause)}})
 return {open(){if(disposed)return;returnFocus=owner.activeElement as HTMLElement;snapshot=JSON.stringify(options.draft.operations);const values=metadataSnapshot(options.info,options.draft.operations,options.draft.identity.sourceSha256),blocked=options.unavailable();for(const key of metadataFields){inputs[key].value=values[key];inputs[key].disabled=blocked!==null}apply.hidden=blocked!==null;cancel.textContent=blocked?'确定':'取消';reason.textContent=blocked??'';error.textContent='';list.replaceChildren();const size=options.fileSize>=1<<20?`${(options.fileSize/(1<<20)).toFixed(1)} MB`:`${Math.max(1,Math.round(options.fileSize/1024))} KB`;for(const [label,value]of [['文件名',options.fileName],['页数',String(options.pageCount())],['文件大小',size],['PDF 版本',options.info.PDFFormatVersion],['创建工具',options.info.Creator],['生成工具',options.info.Producer],['创建时间',fmtDate(options.info.CreationDate)],['修改时间',fmtDate(options.info.ModDate)]] as [string,unknown][]){const term=owner.createElement('dt');term.textContent=label;const detail=owner.createElement('dd');detail.textContent=String(value??'—')||'—';detail.title=detail.textContent;list.append(term,detail)}dialog.showModal();if(!blocked)inputs.title.focus()},incompleteReason:()=>dialog.open?'请先确定或取消文档属性编辑':null,dispose(){disposed=true;trap();dialog.remove()}}
}
