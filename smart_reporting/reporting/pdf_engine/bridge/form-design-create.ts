/** Source-bound Form Design creation and required-property edit, using pinned primitives. */
import {copyDesignField,type FormCopySource} from './form-source-copy'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFArray,PDFDict,PDFName,PDFNumber,PDFRef,PDFRawStream,decodePDFRawStream,PDFTextField,PDFCheckBox,PDFRadioGroup,PDFDropdown} from 'pdf-lib'
import {applyFormFields,applyFormWidgetEdits} from '../src/main/save-pdf'
import {inspectDesignWidgets,formDesignTreeSafe,formDesignContainersUnique} from './form-design'
import {replyReferences} from './note-replies'
import {FORM_DATE_FORMATS,inspectDesignDateActions} from './form-design-actions'
import type {FormFieldInput} from '../src/shared/ipc'
const hash=(input:Uint8Array|string)=>createHash('sha256').update(input).digest('hex')
export interface CreateFormFieldOperation {kind:'createFormField';sourceSha256:string;pageId:string;fieldName:string;fieldKind:'text'|'checkbox'|'date'|'choice'|'radio'|'signature';rect:[number,number,number,number];required:boolean;copyFrom?:FormCopySource;checked?:boolean;value?:string;options?:string[];dateFormat?:typeof FORM_DATE_FORMATS[number];multiLine?:boolean;maxLen?:number;fontSize?:number;textAlignment?:'left'|'center'|'right';radioWidgets?:{pageId:string;rect:[number,number,number,number];exportValue:string;checked?:boolean}[]}
export interface EditFormFieldRequiredOperation {kind:'editFormFieldRequired';sourceSha256:string;fieldName:string;widgetId:string;widgetIdentity:string;expectedWidgetSha256:string;required:boolean}
export async function formDesignCreateAvailability(source:Uint8Array|PDFDocument){
 try{
  const d=source instanceof PDFDocument?source:await PDFDocument.load(source,{updateMetadata:false}),acro=d.catalog.lookupMaybe(PDFName.of('AcroForm'),PDFDict)
  if(d.isEncrypted||d.context.trailerInfo.Encrypt||d.catalog.has(PDFName.of('Perms')))throw Error('受保护或签名权限来源不能设计表单')
  if(acro?.has(PDFName.of('XFA')))throw Error('固定源仅支持 AcroForm，不支持保留或编辑 XFA')
  const references=replyReferences(d,false);if(!references||!formDesignContainersUnique(d,references))throw Error('来源签名或共享表单容器未通过安全复核')
  if(!formDesignTreeSafe(d))throw Error('字段层级存在循环、重复引用或 Parent/Kids 不闭合')
  const owners=new Set<PDFDict>(),trusted=new Set<PDFDict>()
  for(const f of d.getForm().getFields()){
   for(const dict of [f.acroField.dict,...f.acroField.getWidgets().map(w=>w.dict)]){const date=inspectDesignDateActions(dict);if(date){owners.add(dict);date.objects.forEach(o=>trusted.add(o))}}
  }
  const stack:unknown[]=d.context.enumerateIndirectObjects().map(([,o])=>o),seen=new Set<object>();let budget=200000
  while(stack.length){if(--budget<0)throw Error('来源对象图超过安全复核范围');let o=stack.pop();if(o instanceof PDFRawStream)o=o.dict;if(o instanceof PDFDict){if(seen.has(o))continue;seen.add(o);if(['A','OpenAction','JavaScript','XFA','ByteRange'].some(k=>o.has(PDFName.of(k)))||o.has(PDFName.of('AA'))&&!owners.has(o)||o.has(PDFName.of('JS'))&&!trusted.has(o)||String(o.get(PDFName.of('Type')))==='/Sig')throw Error('仅许可精确 AFDate 内建日期动作，其他动作或签名来源不能设计');stack.push(...o.values())}else if(o instanceof PDFArray){if(seen.has(o))continue;seen.add(o);stack.push(...o.asArray())}}
  for(const p of d.getPages()){const unit=p.node.getInheritableAttribute(PDFName.of('UserUnit'));if(unit!==undefined&&(!(unit instanceof PDFNumber)||unit.asNumber()!==1))throw Error('仅支持默认 UserUnit');if(![0,90,180,270].includes(p.getRotation().angle))throw Error('仅支持直角页面旋转')}
  const content=source instanceof PDFDocument?await d.save({useObjectStreams:false,updateFieldAppearances:false}):source,widgets=(await inspectDesignWidgets(content)).widgets
  if(widgets.some(w=>!w.designEditable))throw Error(widgets.find(w=>!w.designEditable)?.designReason||'字段控件身份未通过安全复核')
  const refs=new Set(widgets.map(w=>w.widgetId))
  for(const p of d.getPages())for(const r of p.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray()??[])if(!(r instanceof PDFRef)||!refs.has(r.objectNumber+'R'+(r.generationNumber||'')))throw Error('页面含未确认可保留的非表单注释')
  return {createFormField:true,createFormFieldReason:null}
 }catch(error){return {createFormField:false,createFormFieldReason:error instanceof Error?error.message:'来源未通过表单设计安全复核'}}
}
export function validSource(content:Uint8Array,expected:string,actual:string){if(hash(content)!==expected||actual!==expected)throw Error('pdf_form_design_source_changed')}
export function fieldSnapshot(d:PDFDocument,except?:string){return d.getForm().getFields().filter(f=>f.getName()!==except).map(f=>[String(f.ref),f.acroField.dict.toString(),f.acroField.getWidgets().map(w=>w.dict.toString())])}
// pdf-lib 将三类资源字典内联，并补空字典；比较原有映射而非间接引用的表示方式。
function resourceSnapshot(d:PDFDocument,resources:PDFDict|undefined){
 return (resources?.entries()??[]).flatMap(([key,value])=>{
  const name=String(key),category=['/Font','/XObject','/ExtGState'].includes(name),resolved=category?d.context.lookup(value):value
  if(category&&resolved instanceof PDFDict&&resolved.keys().length===0)return []
  return [[name,String(resolved)]]
 }).sort(([a],[b])=>a.localeCompare(b))
}
export function bodySnapshot(d:PDFDocument){return d.getPages().map(p=>{const raw=p.node.Contents(),streams=raw instanceof PDFArray?raw.asArray():raw?[raw]:[];return {media:p.getMediaBox(),crop:p.getCropBox(),rotation:p.getRotation().angle,resources:resourceSnapshot(d,p.node.Resources()),contents:streams.map(r=>{const stream=d.context.lookup(r);if(!(stream instanceof PDFRawStream))throw Error('unreadable content stream');return Buffer.from(decodePDFRawStream(stream).decode()).toString('base64')}).filter(value=>!['cQo=','UQo='].includes(value))}})}
export function annotationsSnapshot(d:PDFDocument,except?:PDFRef|PDFRef[]){const refs=new Set((Array.isArray(except)?except:except?[except]:[]).map(String));return d.getPages().map(p=>(p.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray()??[]).filter(r=>!refs.has(String(r))).map(String))}
export function receipt(content:Uint8Array,bytes:Uint8Array,op:{kind:string},reason:string|null){const sourceSha256=hash(content),sha256=hash(bytes),skippedOperations=reason?[{operationIndex:0,kind:op.kind,reason}]:[],appliedOperationIndices=reason?[]:[0];return {bytes,sourceSha256,sha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,op,sha256,skippedOperations}))}}
const printable=(v:unknown,max=4000)=>typeof v==='string'&&v.length<=max&&/^[ -~]*$/.test(v)
export function validDesignFieldName(value:unknown):value is string{return typeof value==='string'&&value.length<=256&&value.split('.').length<=16&&value.split('.').every(part=>/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(part))}
export function validateDesignCreation(op:CreateFormFieldOperation){
 const base=['kind','sourceSha256','pageId','fieldName','fieldKind','rect','required',...(op.copyFrom!==undefined?['copyFrom']:[])],text=['value','fontSize','textAlignment','multiLine','maxLen'],allowed=op.copyFrom!==undefined?(op.fieldKind==='radio'?['radioWidgets']:[]):op.fieldKind==='signature'?[]:op.fieldKind==='checkbox'?['checked']:op.fieldKind==='radio'?['radioWidgets']:op.fieldKind==='choice'?['options','value']:op.fieldKind==='date'?[...text,'dateFormat']:text
 if(Object.keys(op).some(k=>![...base,...allowed].includes(k))||op.kind!=='createFormField'||!['text','checkbox','date','choice','radio','signature'].includes(op.fieldKind)||typeof op.required!=='boolean'||!validDesignFieldName(op.fieldName)||op.fieldKind==='signature'&&op.fieldName.includes('.'))throw Error('pdf_form_create_invalid')
 if(op.copyFrom!==undefined){if(!op.copyFrom||!['text','checkbox','choice','date','radio','signature'].includes(op.fieldKind))throw Error('pdf_form_copy_invalid');if(op.fieldKind!=='radio')return}
 if(op.checked!==undefined&&typeof op.checked!=='boolean'||op.value!==undefined&&!printable(op.value)||op.multiLine!==undefined&&typeof op.multiLine!=='boolean'||op.maxLen!==undefined&&(!Number.isInteger(op.maxLen)||op.maxLen<0||op.maxLen>4000)||op.fontSize!==undefined&&(!Number.isFinite(op.fontSize)||op.fontSize<6||op.fontSize>72)||op.textAlignment!==undefined&&!['left','center','right'].includes(op.textAlignment)||op.dateFormat!==undefined&&!FORM_DATE_FORMATS.includes(op.dateFormat)||op.maxLen&&op.value&&op.value.length>op.maxLen)throw Error('pdf_form_create_properties_invalid')
 if(op.fieldKind==='choice'&&(!Array.isArray(op.options)||op.options.length<1||op.options.length>100||op.options.some(v=>!printable(v,200)||!v)||new Set(op.options).size!==op.options.length||op.value!==undefined&&!op.options.includes(op.value)))throw Error('pdf_form_create_options_invalid')
 if(op.fieldKind==='radio'){const list=op.radioWidgets;if(!Array.isArray(list)||list.length<2||list.length>64||list.some(w=>!w||Object.keys(w).some(k=>!['pageId','rect','exportValue','checked'].includes(k))||!printable(w.exportValue,128)||!w.exportValue||w.checked!==undefined&&typeof w.checked!=='boolean')||new Set(list.map(w=>w.exportValue)).size!==list.length||list.filter(w=>w.checked).length>1||list[0].pageId!==op.pageId||JSON.stringify(list[0].rect)!==JSON.stringify(op.rect))throw Error('pdf_form_create_radio_invalid')}
}
export function designRectPage(d:PDFDocument,sourceSha256:string,pageId:string,rect:number[]){
 const index=d.getPages().findIndex((_,i)=>pageId==='sha256:'+sourceSha256+':page:'+i)
 if(index<0||!Array.isArray(rect)||rect.length!==4||!rect.every(v=>typeof v==='number'&&Number.isFinite(v)))throw Error('pdf_form_create_page_invalid')
 const b=d.getPage(index).getCropBox(),[x1,y1,x2,y2]=rect
 if(x2-x1<8||y2-y1<8||x2-x1>2000||y2-y1>2000||x1<b.x||y1<b.y||x2>b.x+b.width||y2>b.y+b.height)throw Error('pdf_form_create_rect_invalid')
 return index
}
// pdf-lib 1.17.1 registers each new nonterminal twice. Drop only this call's unused alias;
// retain the canonical Parent/Kids references and never normalize preexisting source objects.
function discardNewHierarchyAliases(d:PDFDocument,before:Set<string>){
 const objects=d.context.enumerateIndirectObjects(),canonical=new Set(d.getForm().acroForm.getAllFields().map(([,ref])=>String(ref))),groups=new Map<PDFDict,PDFRef[]>(),counts=new Map<string,number>(),seen=new Set<object>(),stack:unknown[]=objects.map(([,object])=>object)
 for(const[ref,object]of objects)if(object instanceof PDFDict){const refs=groups.get(object)??[];refs.push(ref);groups.set(object,refs)}
 while(stack.length){let object=stack.pop();if(object instanceof PDFRef){counts.set(String(object),(counts.get(String(object))??0)+1);continue}if(object instanceof PDFRawStream)object=object.dict;if(object instanceof PDFDict||object instanceof PDFArray){if(seen.has(object))continue;seen.add(object);stack.push(...(object instanceof PDFDict?object.values():object.asArray()))}}
 for(const[dict,refs]of groups)if(refs.length>1&&!dict.has(PDFName.of('FT'))&&dict.has(PDFName.of('Kids'))&&refs.filter(ref=>canonical.has(String(ref))).length===1)for(const ref of refs)if(!canonical.has(String(ref))&&!before.has(String(ref))&&!counts.has(String(ref)))d.context.delete(ref)
}
function fieldTreeSnapshot(d:PDFDocument){return [String(d.getForm().acroForm.dict.get(PDFName.of('Fields'))),d.getForm().acroForm.getAllFields().filter(([field])=>!field.dict.has(PDFName.of('FT'))).map(([field,ref])=>[String(ref),field.dict.toString()])]}
export async function createDesignField(content:Uint8Array,expectedSha256:string,op:CreateFormFieldOperation){
 validSource(content,expectedSha256,op.sourceSha256);validateDesignCreation(op)
 if(op.copyFrom!==undefined)return copyDesignField(content,expectedSha256,op)
 const d=await PDFDocument.load(content,{updateMetadata:false}),availability=await formDesignCreateAvailability(content);if(!availability.createFormField)throw Error(availability.createFormFieldReason||'pdf_form_create_source_unsupported')
 const index=designRectPage(d,expectedSha256,op.pageId,op.rect)
 if(d.getForm().getFields().some(f=>f.getName()===op.fieldName||f.getName().startsWith(op.fieldName+'.')||op.fieldName.startsWith(f.getName()+'.')))throw Error('pdf_form_create_duplicate_or_prefix_name')
 const fields=fieldSnapshot(d),body=bodySnapshot(d),annotations=annotationsSnapshot(d)
 const inputs:FormFieldInput[]=op.fieldKind==='radio'?op.radioWidgets!.map(w=>({name:op.fieldName,kind:'radio',pageIndex:designRectPage(d,expectedSha256,w.pageId,w.rect),rect:w.rect,required:op.required,exportValue:w.exportValue,checked:w.checked??false})):[{name:op.fieldName,kind:op.fieldKind==='date'?'text':op.fieldKind,pageIndex:index,rect:op.rect,required:op.required,...(op.fieldKind==='signature'?{}:op.fieldKind==='checkbox'?{checked:op.checked??false}:op.fieldKind==='choice'?{options:op.options,value:op.value}:{fontSize:op.fontSize??12,textAlignment:op.textAlignment??'left',value:op.value,multiLine:op.multiLine,maxLen:op.maxLen,...(op.fieldKind==='date'?{dateFormat:op.dateFormat??'yyyy-mm-dd'}:{})})}]
 const originalRefs=new Set(d.context.enumerateIndirectObjects().map(([ref])=>String(ref)))
 applyFormFields(d,inputs);discardNewHierarchyAliases(d,originalRefs)
 const expectedTree=fieldTreeSnapshot(d)
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:true});let reason:null|string=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),f=out.getForm().getField(op.fieldName),widgets=f.acroField.getWidgets(),refs=widgets.map(w=>out.context.getObjectRef(w.dict)).filter((v):v is PDFRef=>!!v)
  if(!formDesignTreeSafe(out)||JSON.stringify(fieldTreeSnapshot(out))!==JSON.stringify(expectedTree)||widgets.length!==inputs.length||refs.length!==inputs.length||JSON.stringify(annotationsSnapshot(out,refs))!==JSON.stringify(annotations)||JSON.stringify(fieldSnapshot(out,op.fieldName))!==JSON.stringify(fields)||JSON.stringify(bodySnapshot(out))!==JSON.stringify(body)||widgets.some(w=>op.fieldKind==='signature'?w.dict.has(PDFName.of('AP'))||w.dict.has(PDFName.of('V')):!w.dict.lookupMaybe(PDFName.of('AP'),PDFDict))||f.isRequired()!==op.required||(await inspectDesignWidgets(bytes)).widgets.filter(w=>w.fieldName===op.fieldName&&w.designEditable).length!==inputs.length)throw Error('field tree, appearance or original content changed')
  if(f instanceof PDFTextField&&(f.getText()??'')!==(op.value??'')||f instanceof PDFCheckBox&&f.isChecked()!==(op.checked??false)||f instanceof PDFDropdown&&(JSON.stringify(f.getOptions())!==JSON.stringify(op.options)||JSON.stringify(f.getSelected())!==JSON.stringify(op.value?[op.value]:[]))||f instanceof PDFRadioGroup&&(JSON.stringify(f.getOptions())!==JSON.stringify(op.radioWidgets!.map(w=>w.exportValue))||f.getSelected()!==op.radioWidgets!.find(w=>w.checked)?.exportValue))throw Error('field values or options changed')
  if(op.fieldKind==='date'&&inspectDesignDateActions(f.acroField.dict)?.format!==(op.dateFormat??'yyyy-mm-dd'))throw Error('date actions changed')
 }catch(e){reason='pdf_form_create_output_review_failed: '+String(e)}
 return receipt(content,bytes,op,reason)
}
export async function editDesignFieldRequired(content:Uint8Array,expectedSha256:string,op:EditFormFieldRequiredOperation){
 validSource(content,expectedSha256,op.sourceSha256)
 if(Object.keys(op).some(k=>!['kind','sourceSha256','fieldName','widgetId','widgetIdentity','expectedWidgetSha256','required'].includes(k))||op.kind!=='editFormFieldRequired'||typeof op.required!=='boolean')throw Error('pdf_form_required_invalid')
 const census=await inspectDesignWidgets(content),matches=census.widgets.filter(w=>w.removable&&['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'].every(k=>w[k as keyof typeof w]===op[k as keyof typeof op]))
 if(matches.length!==1||(await formDesignCreateAvailability(content)).createFormField!==true)throw Error('pdf_form_design_widget_invalid_or_readonly')
 const d=await PDFDocument.load(content,{updateMetadata:false}),fields=fieldSnapshot(d,op.fieldName),body=bodySnapshot(d),annotations=annotationsSnapshot(d),target=d.getForm().getField(op.fieldName),widget=target.acroField.getWidgets()[0].dict.toString()
 applyFormWidgetEdits(d,[{fieldName:op.fieldName,widgetId:op.widgetId,required:op.required}]);const expectedField=target.acroField.dict.toString(),expectedWidget=target.acroField.getWidgets()[0].dict.toString()
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:null|string=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),f=out.getForm().getField(op.fieldName);if(JSON.stringify(annotationsSnapshot(out))!==JSON.stringify(annotations)||JSON.stringify(fields)!==JSON.stringify(fieldSnapshot(out,op.fieldName))||JSON.stringify(body)!==JSON.stringify(bodySnapshot(out))||f.acroField.dict.toString()!==expectedField||f.acroField.getWidgets()[0].dict.toString()!==(target.acroField.dict===target.acroField.getWidgets()[0].dict?expectedWidget:widget)||f.isRequired()!==op.required)throw Error('required property or surviving objects changed')}catch(e){reason='pdf_form_required_output_review_failed: '+String(e)}
 return receipt(content,bytes,op,reason)
}
