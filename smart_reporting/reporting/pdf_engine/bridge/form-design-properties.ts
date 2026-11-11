/** 精确已有控件设计；字段名与下拉选项是限定安全范围的原生属性增量。 */
import {PDFDocument,PDFDict,PDFName,PDFRawStream,PDFDropdown,PDFRadioGroup} from 'pdf-lib'
import {applyFormWidgetEdits} from '../src/main/save-pdf'
import {inspectDesignWidgets,inspectDesignChoiceOptions,type DesignWidgetIdentity} from './form-design'
import {formDesignCreateAvailability,validSource,bodySnapshot,annotationsSnapshot,receipt,designRectPage,validDesignFieldName} from './form-design-create'
import {FORM_ARRANGEMENTS,arrangeDesignRects,type FormArrangement} from './form-design-layout'
export interface FormWidgetTarget {fieldName:string;widgetId:string;widgetIdentity:string;expectedWidgetSha256:string}
export interface EditFormWidgetOperation extends FormWidgetTarget {kind:'editFormWidget';sourceSha256:string;rect?:[number,number,number,number];required?:boolean;newFieldName?:string;choiceOptions?:string[]}
export interface ArrangeFormWidgetsOperation {kind:'arrangeFormWidgets';sourceSha256:string;targets:FormWidgetTarget[];alignment:FormArrangement}
const targetKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256']
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)
function validateTarget(target:FormWidgetTarget){if(!target||typeof target.fieldName!=='string'||!target.fieldName||typeof target.widgetId!=='string'||!/^[0-9]+R[0-9]*$/.test(target.widgetId)||!digest(target.widgetIdentity)||!digest(target.expectedWidgetSha256))throw Error('pdf_form_widget_identity_invalid')}
function resolveTarget(widgets:DesignWidgetIdentity[],target:FormWidgetTarget){validateTarget(target);const matches=widgets.filter(w=>w.designEditable&&targetKeys.every(key=>w[key as keyof DesignWidgetIdentity]===target[key as keyof FormWidgetTarget]));if(matches.length!==1)throw Error('pdf_form_widget_stale_or_readonly');return matches[0]}
export async function formDesignPropertiesAvailability(content:Uint8Array){const available=await formDesignCreateAvailability(content),widgets=(await inspectDesignWidgets(content)).widgets.filter(w=>w.designEditable),counts=new Map<number,number>();widgets.forEach(w=>counts.set(w.pageIndex,(counts.get(w.pageIndex)??0)+1));const edit=available.createFormField&&widgets.length>0,arrange=available.createFormField&&[...counts.values()].some(n=>n>=2);return {editFormWidget:edit,editFormWidgetReason:edit?null:available.createFormFieldReason||'来源没有通过身份复核的 AcroForm 控件',arrangeFormWidgets:arrange,arrangeFormWidgetsReason:arrange?null:available.createFormFieldReason||'同一页至少需要两个可设计控件'}}
function widgetState(d:PDFDocument,affected:Set<string>){return d.getForm().getFields().map(f=>[f.getName(),f.acroField.dict.toString(),f.acroField.getWidgets().map(w=>affected.has(f.getName())?w.dict.entries().filter(([key])=>String(key)!=='/AP').map(([key,value])=>[String(key),String(value)]).sort(([a],[b])=>a.localeCompare(b)):w.dict.toString())])}
// A standalone name/options change permits only /T or /Opt; preserve every raw stream/reference.
function renameState(d:PDFDocument,field:PDFDict,except='/T'){return d.context.enumerateIndirectObjects().map(([ref,obj])=>[String(ref),obj instanceof PDFDict&&obj===field?obj.entries().filter(([key])=>String(key)!==except).map(([k,v])=>[String(k),String(v)]):obj instanceof PDFRawStream?obj.dict.toString()+Buffer.from(obj.contents).toString('hex'):String(obj)])}
async function changeChoiceOptions(content:Uint8Array,d:PDFDocument,target:DesignWidgetIdentity,op:EditFormWidgetOperation){
 const options=op.choiceOptions,field=d.getForm().getField(target.fieldName),support=inspectDesignChoiceOptions(field)
 if(!Array.isArray(options)||options.length<1||options.length>100||options.some(v=>typeof v!=='string'||!v||v.length>200||!/^[ -~]+$/.test(v))||new Set(options).size!==options.length||op.rect!==undefined||op.required!==undefined||op.newFieldName!==undefined)throw Error('pdf_form_choice_options_invalid_or_mixed')
 if(!(field instanceof PDFDropdown)||!target.choiceOptionsEditable||!support.editable)throw Error(support.reason||'pdf_form_choice_options_source_unsupported')
 if(JSON.stringify(options)===JSON.stringify(support.options)||[support.value,support.defaultValue].some(value=>value!==null&&value!==undefined&&!options.includes(value)))throw Error('pdf_form_choice_options_must_change_and_preserve_current_default')
 d.getPages();const before=renameState(d,field.acroField.dict,'/Opt'),ref=String(field.ref)
 field.setOptions(options)
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),changed=out.getForm().getDropdown(target.fieldName);out.getPages();const widgets=(await inspectDesignWidgets(bytes)).widgets
  if(String(changed.ref)!==ref||JSON.stringify(changed.getOptions())!==JSON.stringify(options)||JSON.stringify(renameState(out,changed.acroField.dict,'/Opt'))!==JSON.stringify(before)||widgets.filter(w=>w.fieldName===target.fieldName&&w.widgetId===target.widgetId&&w.choiceOptionsEditable).length!==1)throw Error('dropdown options, original value, appearance or objects changed')
 }catch(error){reason='pdf_form_widget_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}
async function renameWidget(content:Uint8Array,d:PDFDocument,target:DesignWidgetIdentity,op:EditFormWidgetOperation,census:DesignWidgetIdentity[]){
 const name=op.newFieldName!,field=d.getForm().getField(target.fieldName),parent=(value:string)=>value.split('.').slice(0,-1).join('.')
 if(!validDesignFieldName(name)||name===target.fieldName||parent(name)!==parent(target.fieldName)||op.rect!==undefined||op.required!==undefined)throw Error('pdf_form_widget_rename_name_invalid_or_mixed')
 const group=census.filter(w=>w.fieldName===target.fieldName),radio=field instanceof PDFRadioGroup&&field.acroField.getWidgets().length>1
 if(field.acroField.getWidgets().length!==1&&(!radio||group.length!==field.acroField.getWidgets().length||!group.every(w=>w.designEditable&&w.radioRenameEditable)))throw Error('pdf_form_widget_rename_requires_single_widget_or_safe_radio_group')
 if(d.getForm().getFields().some(f=>f!==field&&f.getName()!==target.fieldName&&(f.getName()===name||f.getName().startsWith(name+'.')||name.startsWith(f.getName()+'.'))))throw Error('pdf_form_widget_rename_duplicate_or_prefix_name')
 d.getPages();const before=renameState(d,field.acroField.dict),ref=String(field.ref)
 field.acroField.setPartialName(name.split('.').at(-1)!)
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),renamed=out.getForm().getField(name);out.getPages();const widgets=(await inspectDesignWidgets(bytes)).widgets
  if(out.getForm().getFieldMaybe(target.fieldName)||String(renamed.ref)!==ref||JSON.stringify(renameState(out,renamed.acroField.dict))!==JSON.stringify(before)||JSON.stringify(widgets.filter(w=>w.fieldName===name&&w.designEditable&&(!radio||w.radioRenameEditable)).map(w=>w.widgetId).sort())!==JSON.stringify(group.map(w=>w.widgetId).sort()))throw Error('field name, original objects or widget identity changed')
 }catch(error){reason='pdf_form_widget_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}
async function changeRadioRequired(content:Uint8Array,d:PDFDocument,target:DesignWidgetIdentity,op:EditFormWidgetOperation,census:DesignWidgetIdentity[]){
 const field=d.getForm().getField(target.fieldName),group=census.filter(w=>w.fieldName===target.fieldName)
 if(!(field instanceof PDFRadioGroup)||typeof op.required!=='boolean'||op.rect!==undefined||op.newFieldName!==undefined||op.choiceOptions!==undefined||field.isRequired()===op.required)throw Error('pdf_form_radio_required_invalid_mixed_or_unchanged')
 if(group.length<2||group.length>64||group.length!==field.acroField.getWidgets().length||!group.every(w=>w.designEditable&&w.radioRequiredEditable&&w.required===field.isRequired()))throw Error(target.radioRequiredReason||'pdf_form_radio_required_source_unsupported')
 d.getPages();const before=renameState(d,field.acroField.dict,'/Ff'),flags=field.acroField.getFlags(),ref=String(field.ref),ids=group.map(w=>w.widgetId).sort()
 if(op.required)field.enableRequired();else field.disableRequired()
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),changed=out.getForm().getRadioGroup(target.fieldName);out.getPages();const after=(await inspectDesignWidgets(bytes)).widgets.filter(w=>w.fieldName===target.fieldName)
  if(String(changed.ref)!==ref||changed.acroField.getFlags()!==(flags^2)||changed.isRequired()!==op.required||JSON.stringify(renameState(out,changed.acroField.dict,'/Ff'))!==JSON.stringify(before)||JSON.stringify(after.filter(w=>w.designEditable&&w.radioRequiredEditable&&w.required===op.required).map(w=>w.widgetId).sort())!==JSON.stringify(ids))throw Error('required bit, original objects, appearances or surviving widget identities changed')
 }catch(error){reason='pdf_form_widget_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}
async function writeWidgets(content:Uint8Array,expected:string,op:{kind:string},edits:{target:DesignWidgetIdentity;rect?:[number,number,number,number];required?:boolean}[],preserveUntouchedWidgets=false){
 const d=await PDFDocument.load(content,{updateMetadata:false}),body=bodySnapshot(d),annotations=annotationsSnapshot(d),affected=new Set(edits.map(e=>e.target.fieldName)),modified=new Set(edits.map(e=>e.target.widgetId))
 const widgetId=(ref:unknown)=>String(ref).replace(/^(\d+) (\d+) R$/,(_,n,g)=>n+'R'+(g==='0'?'':g))
 const originalState=(doc:PDFDocument)=>new Map(doc.context.enumerateIndirectObjects().map(([ref,obj])=>[String(ref),obj instanceof PDFDict&&modified.has(widgetId(ref))?JSON.stringify(obj.entries().filter(([key])=>!['/Rect','/AP'].includes(String(key))).map(([k,v])=>[String(k),String(v)])):obj instanceof PDFRawStream?obj.dict.toString()+Buffer.from(obj.contents).toString('hex'):String(obj)]))
 const originals=preserveUntouchedWidgets?originalState(d):null,modifiedDicts=new Set(d.context.enumerateIndirectObjects().filter(([ref])=>modified.has(widgetId(ref))).map(([,obj])=>obj)),appearances=preserveUntouchedWidgets?d.getForm().getFields().flatMap(f=>f.acroField.getWidgets()).map(w=>({dict:w.dict,ap:w.dict.get(PDFName.of('AP'))})):[],untouched=appearances.filter(({dict})=>!modifiedDicts.has(dict))
 applyFormWidgetEdits(d,edits.map(e=>({fieldName:e.target.fieldName,widgetId:e.target.widgetId,...(e.rect?{rect:e.rect}:{}),...(e.required!==undefined?{required:e.required}:{})})))
 const expectedState=widgetState(d,affected)
 // Native appearance updates mutate /AP dictionaries in place; detach them first so original references/streams survive.
 if(preserveUntouchedWidgets){for(const {dict}of appearances){const ap=dict.lookupMaybe(PDFName.of('AP'),PDFDict);if(ap)dict.set(PDFName.of('AP'),ap.clone())}d.getForm().updateFieldAppearances();for(const {dict,ap}of untouched){if(ap)dict.set(PDFName.of('AP'),ap);else dict.delete(PDFName.of('AP'))}}
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:!preserveUntouchedWidgets});let reason:string|null=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),census=(await inspectDesignWidgets(bytes)).widgets;if(JSON.stringify(bodySnapshot(out))!==JSON.stringify(body)||JSON.stringify(annotationsSnapshot(out))!==JSON.stringify(annotations)||JSON.stringify(widgetState(out,affected))!==JSON.stringify(expectedState))throw Error('original body, field tree or surviving widgets changed')
  if(originals){const actual=originalState(out);for(const [ref,value]of originals)if(actual.get(ref)!==value)throw Error('original object changed outside arranged Widget geometry/appearance: '+ref)}
  for(const edit of edits){const f=out.getForm().getField(edit.target.fieldName),w=census.find(w=>w.widgetId===edit.target.widgetId&&w.fieldName===edit.target.fieldName);if(!w?.designEditable||edit.rect&&JSON.stringify(w.rect)!==JSON.stringify(edit.rect)||edit.required!==undefined&&f.isRequired()!==edit.required||f.acroField.getWidgets().some(w=>!w.dict.lookupMaybe(PDFName.of('AP'),PDFDict)))throw Error('widget geometry required flag or appearance changed')}
 }catch(error){reason='pdf_form_widget_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}
export async function editDesignWidget(content:Uint8Array,expected:string,op:EditFormWidgetOperation){
 validSource(content,expected,op.sourceSha256)
 if(op.kind!=='editFormWidget'||Object.keys(op).some(k=>!['kind','sourceSha256',...targetKeys,'rect','required','newFieldName','choiceOptions'].includes(k))||op.rect===undefined&&op.required===undefined&&op.newFieldName===undefined&&op.choiceOptions===undefined||op.required!==undefined&&typeof op.required!=='boolean')throw Error('pdf_form_widget_properties_invalid')
 const availability=await formDesignCreateAvailability(content);if(!availability.createFormField)throw Error(availability.createFormFieldReason||'pdf_form_widget_source_unsupported')
 const census=(await inspectDesignWidgets(content)).widgets,target=resolveTarget(census,op),d=await PDFDocument.load(content,{updateMetadata:false});if(op.required!==undefined&&d.getForm().getField(target.fieldName) instanceof PDFRadioGroup)return changeRadioRequired(content,d,target,op,census);if(op.choiceOptions!==undefined)return changeChoiceOptions(content,d,target,op);if(op.newFieldName!==undefined)return renameWidget(content,d,target,op,census);if(op.rect!==undefined)designRectPage(d,expected,'sha256:'+expected+':page:'+target.pageIndex,op.rect)
 return writeWidgets(content,expected,op,[{target,rect:op.rect,required:op.required}])
}
export async function arrangeDesignWidgets(content:Uint8Array,expected:string,op:ArrangeFormWidgetsOperation){
 validSource(content,expected,op.sourceSha256)
 if(op.kind!=='arrangeFormWidgets'||Object.keys(op).some(k=>!['kind','sourceSha256','targets','alignment'].includes(k))||!FORM_ARRANGEMENTS.includes(op.alignment)||!Array.isArray(op.targets)||op.targets.length<(op.alignment.startsWith('distribute')?3:2)||op.targets.length>64||op.targets.some(t=>Object.keys(t).some(k=>!targetKeys.includes(k)))||new Set(op.targets.map(t=>t.widgetId)).size!==op.targets.length)throw Error('pdf_form_arrange_invalid')
 const availability=await formDesignCreateAvailability(content);if(!availability.createFormField)throw Error(availability.createFormFieldReason||'pdf_form_widget_source_unsupported')
 const census=(await inspectDesignWidgets(content)).widgets,targets=op.targets.map(t=>resolveTarget(census,t)),byPage=new Map<number,DesignWidgetIdentity[]>()
 for(const target of targets)byPage.set(target.pageIndex,[...(byPage.get(target.pageIndex)??[]),target])
 const minimum=op.alignment.startsWith('distribute')?3:2,groups=[...byPage].filter(([,widgets])=>widgets.length>=minimum)
 if(!groups.length)throw Error('每页对齐至少两个控件、分布至少三个控件')
 const d=await PDFDocument.load(content,{updateMetadata:false}),edits:{target:DesignWidgetIdentity;rect:[number,number,number,number]}[]=[]
 for(const [pageIndex,widgets]of groups){const page=d.getPage(pageIndex),b=page.getCropBox(),rects=arrangeDesignRects({pw:b.width,ph:b.height,rot:page.getRotation().angle,x0:b.x,y0:b.y},widgets.map(t=>t.rect),op.alignment)
  rects.forEach((rect,i)=>{designRectPage(d,expected,'sha256:'+expected+':page:'+pageIndex,rect);if(JSON.stringify(rect)!==JSON.stringify(widgets[i].rect))edits.push({target:widgets[i],rect})})
 }
 return writeWidgets(content,expected,op,edits,true)
}
