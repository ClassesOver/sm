import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfDesignWidget} from './pdf-form-design'
import type {PdfFormWidgetTarget} from './pdf-form-create'
export interface PdfRadioExtensionModel {sourceSha256:string;pages:{pageId:string;index?:number;cropBox:{x:number;y:number;width:number;height:number}}[];formDesignWidgets?:PdfDesignWidget[];capabilities?:{appendRadioWidget?:boolean;appendRadioWidgetReason?:string|null}}
export interface PdfRadioExtensionInput {pageId:string;rect:[number,number,number,number];exportValue:string}
const identityKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'] as const
const alone='追加单选控件须单独保存，请先保存或撤销其他修改'
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)
function identityValid(value:Record<string,unknown>){return typeof value.fieldName==='string'&&!!value.fieldName&&value.fieldName.length<=256&&typeof value.widgetId==='string'&&/^[0-9]+R[0-9]*$/.test(value.widgetId)&&digest(value.widgetIdentity)&&digest(value.expectedWidgetSha256)}
function rectValid(value:unknown):value is [number,number,number,number]{return Array.isArray(value)&&value.length===4&&value.every(v=>typeof v==='number'&&Number.isFinite(v))&&value[2]-value[0]>=8&&value[3]-value[1]>=8&&value[2]-value[0]<=2000&&value[3]-value[1]<=2000}
function eligible(model:PdfRadioExtensionModel,w:PdfDesignWidget){const group=model.formDesignWidgets?.filter(v=>v.fieldName===w.fieldName)??[];return w.designEditable===true&&w.fieldKind==='radio'&&group.length<64&&group.every(v=>v.designEditable===true&&v.fieldKind==='radio')&&!!w.radioOptions&&w.radioOptions.length===group.length&&new Set(w.radioOptions).size===w.radioOptions.length}
export function validatePdfRadioExtension(operations:NativeOperation[]){
 const ops=operations.filter(op=>op.kind==='appendRadioWidget');if(!ops.length)return
 if(operations.length!==1)throw Error(alone)
 const op=ops[0]
 if(Object.keys(op).some(k=>!['kind','sourceSha256',...identityKeys,'pageId','rect','exportValue'].includes(k))||!digest(op.sourceSha256)||!identityValid(op)||typeof op.pageId!=='string'||!op.pageId||!rectValid(op.rect)||typeof op.exportValue!=='string'||!op.exportValue||op.exportValue.length>128||!/^[ -~]+$/.test(op.exportValue))throw Error('单选追加身份、区域或选项无效；选项限可打印 ASCII')
}
export function stagePdfRadioExtension(model:PdfRadioExtensionModel,operations:NativeOperation[],target:PdfFormWidgetTarget,input:PdfRadioExtensionInput):NativeOperation[]{
 if(operations.length)throw Error(alone)
 if(model.capabilities?.appendRadioWidget!==true)throw Error(model.capabilities?.appendRadioWidgetReason||'来源没有可追加的安全单选组')
 if(Object.keys(target).some(k=>!identityKeys.includes(k as typeof identityKeys[number]))||Object.keys(input).some(k=>!['pageId','rect','exportValue'].includes(k)))throw Error('单选追加包含未支持属性')
 const next=[{kind:'appendRadioWidget',sourceSha256:model.sourceSha256,...target,...input}];validatePdfRadioExtension(next)
 const matches=model.formDesignWidgets?.filter(w=>eligible(model,w)&&identityKeys.every(k=>w[k]===target[k]))??[]
 if(matches.length!==1)throw Error('单选组完整身份已变化或暂不能追加')
 if(matches[0].radioOptions?.includes(input.exportValue))throw Error('单选导出值重复')
 const page=model.pages.find(p=>p.pageId===input.pageId),box=page?.cropBox,r=input.rect
 if(!box||r[0]<box.x||r[1]<box.y||r[2]>box.x+box.width||r[3]>box.y+box.height)throw Error('追加页面身份已变化或区域超出来源页面')
 return next
}
export function validateRestoredPdfRadioExtension(model:PdfRadioExtensionModel,operations:NativeOperation[]){
 if(!operations.some(op=>op.kind==='appendRadioWidget'))return
 validatePdfRadioExtension(operations);const op=operations[0]
 if(op.sourceSha256!==model.sourceSha256)throw Error('单选追加来源身份已变化')
 const target=Object.fromEntries(identityKeys.map(k=>[k,op[k]])) as unknown as PdfFormWidgetTarget
 stagePdfRadioExtension(model,[],target,{pageId:op.pageId as string,rect:op.rect as [number,number,number,number],exportValue:op.exportValue as string})
}
export function bindPdfRadioExtensionPanel(options:{root:HTMLElement;draft:NativeDraft;model:()=>PdfRadioExtensionModel;activePageId:()=>string;unavailable:()=>string|null;refresh:()=>Promise<void>}){
 const doc=options.root.ownerDocument,panel=doc.createElement('section');panel.className='pdf-form-radio-extension-panel';panel.hidden=true;panel.setAttribute('aria-label','追加单选选项')
 const heading=doc.createElement('h3');heading.textContent='追加单选选项';const help=doc.createElement('p');help.textContent='向当前已保存的单选组追加一个真实控件；保留已有选项、选择、必填属性和外观。新控件初始不选中，选项限可打印 ASCII。坐标为 PDF 左下角原点。'
 const close=doc.createElement('button');close.type='button';close.textContent='关闭追加单选选项';close.onclick=()=>{panel.hidden=true}
 const body=doc.createElement('div'),status=doc.createElement('p');status.setAttribute('role','status');panel.append(heading,help,close,status,body);options.root.append(panel)
 let disposed=false,renderedKey=''
 const key=()=>JSON.stringify([options.draft.operations,options.draft.closed,options.draft.saving,options.unavailable(),options.model()])
 function field(label:string,type='text'){const wrapper=doc.createElement('label'),input=doc.createElement('input');wrapper.textContent=label;input.type=type;input.setAttribute('aria-label',label);wrapper.append(input);body.append(wrapper);return input}
 function select(label:string){const wrapper=doc.createElement('label'),input=doc.createElement('select');wrapper.textContent=label;input.setAttribute('aria-label',label);wrapper.append(input);body.append(wrapper);return input}
 function render(){if(disposed)return;renderedKey=key();body.replaceChildren();const model=options.model(),seen=new Set<string>(),groups=(model.formDesignWidgets??[]).filter(w=>{if(!eligible(model,w)||seen.has(w.fieldName))return false;seen.add(w.fieldName);return true}),group=select('单选组'),page=select('目标页面')
  for(const w of groups){const item=doc.createElement('option');item.value=w.widgetIdentity;item.textContent=w.fieldName+'（已有：'+w.radioOptions!.join(', ')+'；当前：'+(w.radioValue??'未选择')+'）';group.append(item)}
  for(const[pIndex,p]of model.pages.entries()){const item=doc.createElement('option');item.value=p.pageId;item.textContent='第'+((p.index??pIndex)+1)+'页';page.append(item)}page.value=options.activePageId()
  const value=field('新增选项值'),controls=['左下角 X','左下角 Y','宽度','高度'].map(label=>field(label,'number'))
  const resetRect=()=>{const b=model.pages.find(p=>p.pageId===page.value)?.cropBox;for(const[i,v]of [b?b.x+10:10,b?b.y+10:10,20,20].entries()){controls[i].value=String(v);controls[i].step='any'}};resetRect();page.onchange=resetRect
  const apply=doc.createElement('button');apply.type='button';apply.textContent='追加单选控件';apply.dataset.pdfRadioExtensionApply='true';apply.disabled=!!options.unavailable()||options.draft.closed||options.draft.saving||options.draft.dirty||model.capabilities?.appendRadioWidget!==true||!groups.length;body.append(apply)
  status.textContent=options.unavailable()??(options.draft.dirty?alone:model.capabilities?.appendRadioWidgetReason??'')
  apply.onclick=()=>{void stage(group.value,page.value,value.value,controls.map(c=>c.value.trim()===''?NaN:Number(c.value)))}
 }
 async function stage(identity:string,pageId:string,exportValue:string,numbers:number[]){if(disposed||panel.hidden)return;let staged=false;try{
  if(options.unavailable()||options.draft.closed||options.draft.saving||options.draft.dirty)throw Error(options.unavailable()||alone)
  const model=options.model();if(model.sourceSha256!==options.draft.identity.sourceSha256)throw Error('PDF 来源已变化，请重新打开修订')
  const w=model.formDesignWidgets?.find(w=>w.widgetIdentity===identity);if(!w)throw Error('单选组身份已变化')
  const target=Object.fromEntries(identityKeys.map(k=>[k,w[k]])) as unknown as PdfFormWidgetTarget,[x,y,width,height]=numbers
  options.draft.setOperations(stagePdfRadioExtension(model,options.draft.operations,target,{pageId,rect:[x,y,x+width,y+height],exportValue}));staged=true;await options.refresh();if(!disposed){render();status.textContent='单选控件已加入草稿，请核对实际 PDF 预览后保存'}
 }catch(error){if(!disposed){render();status.textContent=(staged?'单选控件已加入草稿，草稿已保留；':'')+(error instanceof Error?error.message:String(error))}}}
 return {element:panel,open(){if(!disposed){panel.hidden=false;render()}},refresh(){if(!panel.hidden&&renderedKey!==key())render()},dispose(){disposed=true;panel.remove()}}
}
