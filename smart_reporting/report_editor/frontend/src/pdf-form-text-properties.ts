import {createPdfFormSettingsPanel} from './pdf-form-settings-panel'
import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfDesignWidget} from './pdf-form-design'
import type {PdfFormWidgetTarget} from './pdf-form-create'
export interface PdfFormTextPropertiesModel {sourceSha256:string;formDesignWidgets?:PdfDesignWidget[];capabilities?:{editFormTextProperties?:boolean;editFormTextPropertiesReason?:string|null}}
export const pdfFormTextFontNames=['Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'] as const
export interface PdfFormTextPropertiesInput {multiLine?:boolean;maxLen?:number;textAlignment?:'left'|'center'|'right';fontSize?:number;fontName?:typeof pdfFormTextFontNames[number]}
const identityKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'] as const
const propertyKeys=['multiLine','maxLen','textAlignment','fontSize','fontName'] as const
const alone='文本属性须单独保存，请先保存或撤销其他修改'
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)
function eligible(w:PdfDesignWidget){return w.designEditable===true&&w.fieldKind==='text'&&w.textPropertiesEditable===true&&!!w.textProperties}
export function validatePdfFormTextProperties(operations:NativeOperation[]){
 const ops=operations.filter(op=>op.kind==='editFormTextProperties');if(!ops.length)return
 if(operations.length!==1)throw Error(alone)
 const op=ops[0]
 if(Object.keys(op).some(k=>!['kind','sourceSha256',...identityKeys,...propertyKeys].includes(k))||!digest(op.sourceSha256)||typeof op.fieldName!=='string'||!op.fieldName||op.fieldName.length>256||typeof op.widgetId!=='string'||!/^\d+R\d*$/.test(op.widgetId)||!digest(op.widgetIdentity)||!digest(op.expectedWidgetSha256)||!propertyKeys.some(k=>Object.hasOwn(op,k))||Object.hasOwn(op,'multiLine')&&typeof op.multiLine!=='boolean'||Object.hasOwn(op,'maxLen')&&(!Number.isInteger(op.maxLen)||Number(op.maxLen)<0||Number(op.maxLen)>4000)||Object.hasOwn(op,'textAlignment')&&!['left','center','right'].includes(op.textAlignment as string)||Object.hasOwn(op,'fontName')&&!pdfFormTextFontNames.includes(op.fontName as typeof pdfFormTextFontNames[number])||Object.hasOwn(op,'fontSize')&&(typeof op.fontSize!=='number'||!Number.isFinite(op.fontSize)||op.fontSize<6||op.fontSize>72))throw Error('文本字段身份或属性无效；长度限 0–4000，字号限 6–72')
}
export function stagePdfFormTextProperties(model:PdfFormTextPropertiesModel,operations:NativeOperation[],target:PdfFormWidgetTarget,properties:PdfFormTextPropertiesInput):NativeOperation[]{
 if(operations.length)throw Error(alone)
 if(model.capabilities?.editFormTextProperties!==true)throw Error(model.capabilities?.editFormTextPropertiesReason||'没有可安全编辑文本属性的字段')
 if(Object.keys(target).some(k=>!identityKeys.includes(k as typeof identityKeys[number]))||Object.keys(properties).some(k=>!propertyKeys.includes(k as typeof propertyKeys[number])))throw Error('文本属性包含未支持内容')
 const next=[{kind:'editFormTextProperties',sourceSha256:model.sourceSha256,...target,...properties}];validatePdfFormTextProperties(next)
 const matches=model.formDesignWidgets?.filter(w=>eligible(w)&&identityKeys.every(k=>w[k]===target[k]))??[]
 if(matches.length!==1)throw Error('文本字段完整身份已变化或暂不能编辑')
 if(properties.maxLen&&properties.maxLen<matches[0].textProperties!.valueLength)throw Error('最大长度不能小于当前文本长度；不会截断现有内容')
 return next
}
export function validateRestoredPdfFormTextProperties(model:PdfFormTextPropertiesModel,operations:NativeOperation[]){
 if(!operations.some(op=>op.kind==='editFormTextProperties'))return
 validatePdfFormTextProperties(operations);const op=operations[0]
 if(op.sourceSha256!==model.sourceSha256)throw Error('文本属性来源身份已变化')
 const target=Object.fromEntries(identityKeys.map(k=>[k,op[k]])) as unknown as PdfFormWidgetTarget
 const properties=Object.fromEntries(propertyKeys.filter(k=>Object.hasOwn(op,k)).map(k=>[k,op[k]])) as PdfFormTextPropertiesInput
 stagePdfFormTextProperties(model,[],target,properties)
}
export function bindPdfFormTextPropertiesPanel(options:{root:HTMLElement;draft:NativeDraft;model:()=>PdfFormTextPropertiesModel;unavailable:()=>string|null;refresh:()=>Promise<void>}){
 const ui=createPdfFormSettingsPanel(options.root,'pdf-form-text-properties-panel','文本字段属性','编辑安全的独立文本控件；保留原值，可选择 Helvetica/Times/Courier 的标准常规与粗斜体字型。每次单独保存，长度不能小于现有内容。当前不支持自定义字体、中文字体、只读或动作字段。','关闭文本属性'),{panel,body,status}=ui,doc=options.root.ownerDocument
 let disposed=false,renderedKey=''
 const key=()=>JSON.stringify([options.draft.operations,options.draft.closed,options.draft.saving,options.unavailable(),options.model()])
 function input(label:string,type:string){const wrapper=doc.createElement('label'),control=doc.createElement('input');wrapper.textContent=label;control.type=type;control.setAttribute('aria-label',label);wrapper.append(control);body.append(wrapper);return control}
 function select(label:string){const wrapper=doc.createElement('label'),control=doc.createElement('select');wrapper.textContent=label;control.setAttribute('aria-label',label);wrapper.append(control);body.append(wrapper);return control}
 function render(){if(disposed)return;ui.render(()=>{renderBody();body.disabled=!!options.unavailable()||options.draft.closed||options.draft.saving||options.draft.dirty||options.model().capabilities?.editFormTextProperties!==true||!body.querySelector<HTMLSelectElement>('select')?.options.length})}
 function renderBody(){if(disposed)return;renderedKey=key();body.replaceChildren();const model=options.model(),widgets=(model.formDesignWidgets??[]).filter(eligible),field=select('文本字段')
  for(const w of widgets){const item=doc.createElement('option');item.value=w.widgetIdentity;item.textContent=w.fieldName+'（'+w.textProperties!.fontName+'）';field.append(item)}
  const multiLine=input('多行文本','checkbox'),maxLen=input('最大长度（0为不限）','number'),alignment=select('文字对齐'),fontName=select('字体'),fontSize=input('字号','number');maxLen.min='0';maxLen.max='4000';maxLen.step='1';fontSize.min='6';fontSize.max='72';fontSize.step='any'
  for(const[value,label]of [['left','左对齐'],['center','居中'],['right','右对齐']]){const item=doc.createElement('option');item.value=value;item.textContent=label;alignment.append(item)}
  for(const value of pdfFormTextFontNames){const item=doc.createElement('option');item.value=value;item.textContent=value;fontName.append(item)}
  const fill=()=>{const p=widgets.find(w=>w.widgetIdentity===field.value)?.textProperties;if(p){multiLine.checked=p.multiLine;maxLen.value=String(p.maxLen??0);alignment.value=p.textAlignment;fontSize.value=String(p.fontSize);fontName.value=p.fontName}};fill();field.onchange=fill
  const apply=doc.createElement('button');apply.type='button';apply.textContent='应用文本属性';apply.dataset.pdfFormTextPropertiesApply='true';apply.disabled=!!options.unavailable()||options.draft.closed||options.draft.saving||options.draft.dirty||model.capabilities?.editFormTextProperties!==true||!widgets.length;body.append(apply)
  status.textContent=options.unavailable()??(options.draft.dirty?alone:model.capabilities?.editFormTextPropertiesReason??'')
  apply.onclick=()=>{const p=widgets.find(w=>w.widgetIdentity===field.value)?.textProperties;if(!p)return;const changed:PdfFormTextPropertiesInput={};if(multiLine.checked!==p.multiLine)changed.multiLine=multiLine.checked;const length=maxLen.value.trim()===''?NaN:Number(maxLen.value);if(length!==(p.maxLen??0))changed.maxLen=length;if(alignment.value!==p.textAlignment)changed.textAlignment=alignment.value as 'left'|'center'|'right';if(fontName.value!==p.fontName)changed.fontName=fontName.value as PdfFormTextPropertiesInput['fontName'];const size=fontSize.value.trim()===''?NaN:Number(fontSize.value);if(size!==p.fontSize)changed.fontSize=size;void stage(field.value,changed)}
 }
 async function stage(identity:string,properties:PdfFormTextPropertiesInput){if(disposed||panel.hidden)return;let staged=false;try{
  if(options.unavailable()||options.draft.closed||options.draft.saving||options.draft.dirty)throw Error(options.unavailable()||alone)
  if(!Object.keys(properties).length)throw Error('至少修改一项文本属性')
  const model=options.model();if(model.sourceSha256!==options.draft.identity.sourceSha256)throw Error('PDF 来源已变化，请重新打开修订')
  const w=model.formDesignWidgets?.find(w=>w.widgetIdentity===identity);if(!w)throw Error('文本字段身份已变化')
  const target=Object.fromEntries(identityKeys.map(k=>[k,w[k]])) as unknown as PdfFormWidgetTarget
  options.draft.setOperations(stagePdfFormTextProperties(model,options.draft.operations,target,properties));staged=true;render();await options.refresh();if(!disposed){render();status.textContent='文本属性已加入草稿，请核对实际 PDF 预览后保存'}
 }catch(error){if(!disposed){if(staged||renderedKey!==key())render();status.textContent=(staged?'文本属性已加入草稿，草稿已保留；':'')+(error instanceof Error?error.message:String(error))}}}
 return {element:panel,open(){if(!disposed){ui.open();render()}},refresh(){if(!panel.hidden&&renderedKey!==key())render()},dispose(){disposed=true;ui.dispose()}}
}
