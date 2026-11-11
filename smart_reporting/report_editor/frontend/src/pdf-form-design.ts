import type { NativeDraft, NativeOperation } from './native-draft'

export interface PdfDesignWidget {
  fieldName:string;widgetId:string;widgetIdentity:string;expectedWidgetSha256:string
  designEditable?:boolean;designReason?:string|null;fieldKind?:string;dateFormat?:string;required?:boolean;radioOptions?:string[];radioValue?:string|null
  radioRenameEditable?:boolean;radioRenameReason?:string|null
  radioRemovalEditable?:boolean;radioRemovalReason?:string|null
  radioRequiredEditable?:boolean;radioRequiredReason?:string|null
  textPropertiesEditable?:boolean;textPropertiesReason?:string|null
  textProperties?:{multiLine:boolean;maxLen:number|null;textAlignment:'left'|'center'|'right';fontSize:number;fontName:string;valueLength:number}
  choiceOptionsEditable?:boolean;choiceOptionsReason?:string|null;choiceOptions?:string[];choiceValue?:string|null;choiceDefaultValue?:string|null
  pageIndex:number;rect:[number,number,number,number];removable:boolean;removalReason:string|null
}
export interface PdfFormDesignModel {
  sourceSha256:string
  formDesignWidgets?:PdfDesignWidget[]
  capabilities?:{removeFormWidget?:boolean}
}
export const PDF_FORM_DESIGN_ALONE_REASON='删除表单控件须单独保存，请先保存或撤销其他修改'

export function validatePdfFormWidgetRemoval(operations:NativeOperation[]) {
  const removals=operations.filter(operation=>operation.kind==='removeFormWidget')
  if(!removals.length)return
  if(operations.length!==1)throw Error(PDF_FORM_DESIGN_ALONE_REASON)
  const op=removals[0]!
  if(Object.keys(op).some(key=>!['kind','sourceSha256','fieldName','widgetId','widgetIdentity','expectedWidgetSha256'].includes(key))
    ||typeof op.fieldName!=='string'||!op.fieldName||op.fieldName.length>256
    ||typeof op.widgetId!=='string'||!/^\d+R\d*$/.test(op.widgetId)
    ||['sourceSha256','widgetIdentity','expectedWidgetSha256'].some(key=>typeof op[key]!=='string'||!/^[a-f0-9]{64}$/.test(op[key] as string)))throw Error('表单控件身份无效，请重新打开修订')
}

function canRemove(model:PdfFormDesignModel,widget:PdfDesignWidget){
 if(widget.removable)return true
 const group=model.formDesignWidgets?.filter(w=>w.fieldName===widget.fieldName)??[],options=widget.radioOptions,value=widget.radioValue
 return widget.radioRemovalEditable===true&&group.length>=2&&group.length<=64&&Array.isArray(options)&&options.length===group.length&&new Set(options).size===group.length&&value!==undefined&&(value===null||options.includes(value))&&new Set(group.map(w=>w.widgetId)).size===group.length&&group.every(w=>w.designEditable===true&&w.fieldKind==='radio'&&JSON.stringify(w.radioOptions)===JSON.stringify(options)&&w.radioValue===value)
}

export function stagePdfFormWidgetRemoval(model:PdfFormDesignModel,operations:NativeOperation[],widgetIdentity:string):NativeOperation[] {
  if(operations.length)throw Error(PDF_FORM_DESIGN_ALONE_REASON)
  const matches=model.formDesignWidgets?.filter(widget=>widget.widgetIdentity===widgetIdentity)??[]
  if(model.capabilities?.removeFormWidget!==true||matches.length!==1||!canRemove(model,matches[0]!))throw Error('表单控件身份已变化或暂不支持删除')
  const widget=matches[0]!
  const next=[{kind:'removeFormWidget',sourceSha256:model.sourceSha256,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256}]
  validatePdfFormWidgetRemoval(next)
  return next
}

export function bindPdfFormDesignPanel(options:{
  root:HTMLElement;draft:NativeDraft;model:()=>PdfFormDesignModel
  unavailable:()=>string|null;refresh:()=>Promise<void>
}) {
  const owner=options.root.ownerDocument
  const panel=owner.createElement('section');panel.className='pdf-form-design-panel';panel.hidden=true;panel.setAttribute('aria-label','表单字段设计')
  const heading=owner.createElement('h3');heading.textContent='表单字段设计'
  const hint=owner.createElement('p');hint.textContent='支持删除安全的独立单控件字段，或安全单选组中未选中且非默认的单个按钮（至少保留一个）。每次删除须单独保存；可撤销，原修订保留。删除不保证擦除旧字段值。'
  const close=owner.createElement('button');close.type='button';close.textContent='关闭字段设计'
  const status=owner.createElement('p');status.setAttribute('role','status')
  const list=owner.createElement('ul')
  panel.append(heading,hint,close,status,list);options.root.append(panel)
  let disposed=false
  close.addEventListener('click',()=>{panel.hidden=true})
  function render() {
    if(disposed)return
    list.replaceChildren()
    const model=options.model(),reason=options.unavailable()
    status.textContent=reason??(options.draft.operations.some(op=>op.kind==='removeFormWidget')?'字段删除已加入草稿，请核对实际预览后保存':options.draft.dirty?PDF_FORM_DESIGN_ALONE_REASON:'')
    const widgets=model.formDesignWidgets??[]
    if(!widgets.length){const empty=owner.createElement('li');empty.textContent='没有可读取的表单控件';list.append(empty)}
    for(const widget of widgets){
      const row=owner.createElement('li'),label=owner.createElement('span'),button=owner.createElement('button')
      const reason=widget.fieldKind==='radio'?widget.radioRemovalReason:widget.removalReason
      label.textContent=`${widget.fieldName} · ${widget.widgetId}（第${widget.pageIndex+1}页）${reason?'：'+reason:''}`
      button.type='button';button.textContent=widget.fieldKind==='radio'?'删除单选按钮':'删除字段';button.dataset.pdfFormWidgetRemove=widget.widgetIdentity
      button.disabled=!!reason||options.draft.closed||options.draft.saving||options.draft.dirty||!canRemove(model,widget)||model.capabilities?.removeFormWidget!==true
      button.addEventListener('click',()=>{void stage(widget.widgetIdentity)})
      row.append(label,button);list.append(row)
    }
  }
  async function stage(widgetIdentity:string) {
    if(disposed||panel.hidden)return
    let staged=false
    try{
      const reason=options.unavailable()
      if(reason)throw Error(reason)
      const model=options.model()
      if(model.sourceSha256!==options.draft.identity.sourceSha256)throw Error('PDF 来源已变化，请重新打开修订')
      options.draft.setOperations(stagePdfFormWidgetRemoval(model,options.draft.operations,widgetIdentity));staged=true;render()
      await options.refresh()
      if(!disposed)render()
    }catch(error){
      if(!disposed){render();status.textContent=`${staged?'字段删除已加入草稿，草稿已保留；':''}${error instanceof Error?error.message:String(error)}`}
    }
  }
  return {element:panel,open(){if(!disposed){panel.hidden=false;render()}},refresh:render,dispose(){if(disposed)return;disposed=true;panel.remove()}}
}
