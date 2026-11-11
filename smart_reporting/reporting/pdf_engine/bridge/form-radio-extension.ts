/** 固定源 applyFormFields 已支持复用 radio；本适配器只增加一个未选中的安全控件。 */
import {PDFDocument,PDFRadioGroup,PDFDict,PDFRef,PDFName,PDFRawStream,decodePDFRawStream} from 'pdf-lib'
import {applyFormFields} from '../src/main/save-pdf'
import {inspectDesignWidgets,formDesignTreeSafe} from './form-design'
import {formDesignCreateAvailability,validSource,designRectPage,bodySnapshot,fieldSnapshot,annotationsSnapshot,receipt} from './form-design-create'
export interface AppendRadioWidgetOperation {kind:'appendRadioWidget';sourceSha256:string;fieldName:string;widgetId:string;widgetIdentity:string;expectedWidgetSha256:string;pageId:string;rect:[number,number,number,number];exportValue:string}
const identityKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'] as const
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)
export function validateAppendRadioWidgetOperation(op:AppendRadioWidgetOperation){
 if(!op||op.kind!=='appendRadioWidget'||Object.keys(op).some(k=>!['kind','sourceSha256',...identityKeys,'pageId','rect','exportValue'].includes(k))||!digest(op.sourceSha256)||!digest(op.widgetIdentity)||!digest(op.expectedWidgetSha256)||typeof op.fieldName!=='string'||!op.fieldName||op.fieldName.length>256||typeof op.widgetId!=='string'||!/^\d+R\d*$/.test(op.widgetId)||typeof op.pageId!=='string'||!op.pageId||typeof op.exportValue!=='string'||!op.exportValue||op.exportValue.length>128||!/^[ -~]+$/.test(op.exportValue)||!Array.isArray(op.rect)||op.rect.length!==4||op.rect.some(v=>typeof v!=='number'||!Number.isFinite(v)))throw Error('pdf_radio_extension_invalid')
}
export async function formRadioExtensionAvailability(content:Uint8Array){
 const availability=await formDesignCreateAvailability(content)
 if(!availability.createFormField)return {appendRadioWidget:false,appendRadioWidgetReason:availability.createFormFieldReason}
 const widgets=(await inspectDesignWidgets(content)).widgets,available=widgets.some(w=>w.designEditable&&w.fieldKind==='radio'&&widgets.filter(v=>v.fieldName===w.fieldName).length<64&&w.radioOptions&&new Set(w.radioOptions).size===w.radioOptions.length)
 return {appendRadioWidget:available,appendRadioWidgetReason:available?null:'来源没有可追加的安全单选组，或已达64控件/含重复导出值'}
}
function appearanceSnapshot(d:PDFDocument,dict:PDFDict):unknown{
 const seen=new Set<string>()
 function read(value:unknown):unknown{if(value instanceof PDFRef){if(seen.has(String(value)))return ['ref',String(value)];seen.add(String(value));return ['ref',String(value),read(d.context.lookup(value))]}if(value instanceof PDFRawStream)return ['stream',value.dict.toString(),Buffer.from(decodePDFRawStream(value).decode()).toString('base64')];if(value instanceof PDFDict)return value.entries().map(([key,value])=>[String(key),read(value)]);return String(value)}
 return read(dict.get(PDFName.of('AP')))
}
export async function appendDesignRadioWidget(content:Uint8Array,expectedSha256:string,op:AppendRadioWidgetOperation){
 validSource(content,expectedSha256,op.sourceSha256);validateAppendRadioWidgetOperation(op)
 const availability=await formDesignCreateAvailability(content);if(!availability.createFormField)throw Error(availability.createFormFieldReason||'pdf_radio_extension_source_unsupported')
 const census=(await inspectDesignWidgets(content)).widgets,matches=census.filter(w=>w.designEditable&&w.fieldKind==='radio'&&identityKeys.every(k=>w[k]===op[k]))
 if(matches.length!==1)throw Error('pdf_radio_extension_stale_or_readonly')
 const d=await PDFDocument.load(content,{updateMetadata:false}),f=d.getForm().getField(op.fieldName)
 if(!(f instanceof PDFRadioGroup)||f.isReadOnly()||f.acroField.getWidgets().length>=64)throw Error('pdf_radio_extension_group_unsupported')
 const options=f.getOptions(),selected=f.getSelected(),required=f.isRequired(),oldWidgets=f.acroField.getWidgets().map(w=>[w.dict.toString(),appearanceSnapshot(d,w.dict)]),oldRefs=f.acroField.Kids()!.asArray().map(String)
 if(options.length!==oldWidgets.length||new Set(options).size!==options.length||options.includes(op.exportValue))throw Error('pdf_radio_extension_duplicate_or_ambiguous_option')
 const index=designRectPage(d,expectedSha256,op.pageId,op.rect),body=bodySnapshot(d),fields=fieldSnapshot(d,op.fieldName),annots=annotationsSnapshot(d)
 applyFormFields(d,[{name:op.fieldName,kind:'radio',pageIndex:index,rect:op.rect,exportValue:op.exportValue,checked:false}])
 const expectedField=f.acroField.dict.toString(),bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),field=out.getForm().getRadioGroup(op.fieldName),widgets=field.acroField.getWidgets(),newWidget=widgets.at(-1)!,newRef=out.context.getObjectRef(newWidget.dict),after=(await inspectDesignWidgets(bytes)).widgets.filter(w=>w.fieldName===op.fieldName)
  if(!formDesignTreeSafe(out)||field.acroField.dict.toString()!==expectedField||JSON.stringify(fieldSnapshot(out,op.fieldName))!==JSON.stringify(fields)||JSON.stringify(bodySnapshot(out))!==JSON.stringify(body)||JSON.stringify(widgets.slice(0,-1).map(w=>[w.dict.toString(),appearanceSnapshot(out,w.dict)]))!==JSON.stringify(oldWidgets)||JSON.stringify(field.acroField.Kids()!.asArray().slice(0,-1).map(String))!==JSON.stringify(oldRefs)||!newRef||JSON.stringify(annotationsSnapshot(out,newRef))!==JSON.stringify(annots)||JSON.stringify(field.getOptions())!==JSON.stringify([...options,op.exportValue])||field.getSelected()!==selected||field.isRequired()!==required||widgets.length!==oldWidgets.length+1||String(newWidget.dict.get(PDFName.of('AS')))!=='/Off'||!newWidget.dict.lookupMaybe(PDFName.of('AP'),PDFDict)||after.length!==widgets.length||after.some(w=>!w.designEditable)||!after.some(w=>w.widgetId===newRef.objectNumber+'R'+(newRef.generationNumber||'')&&w.pageIndex===index&&JSON.stringify(w.rect)===JSON.stringify(op.rect)))throw Error('radio value, appearances, field tree or surviving content changed')
 }catch(error){reason='pdf_radio_extension_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}
