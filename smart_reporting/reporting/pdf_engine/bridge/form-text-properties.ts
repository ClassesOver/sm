/** 精确来源上的单文本控件属性；只调用 pdf-lib setter 和目标 updateAppearances。 */
import {createHash} from 'node:crypto'
import {PDFDocument,PDFDict,PDFName,PDFRawStream,PDFTextField,StandardFonts} from 'pdf-lib'
import {inspectDesignWidgets,inspectDesignTextProperties,formDesignTreeSafe,designTextFontNames} from './form-design'
import {formDesignCreateAvailability,validSource,bodySnapshot,annotationsSnapshot,receipt} from './form-design-create'
import {inspectFormTextOverflow} from '../src/main/form-text-properties'
export interface EditFormTextPropertiesOperation {kind:'editFormTextProperties';sourceSha256:string;fieldName:string;widgetId:string;widgetIdentity:string;expectedWidgetSha256:string;multiLine?:boolean;maxLen?:number;textAlignment?:'left'|'center'|'right';fontSize?:number;fontName?:typeof designTextFontNames[number]}
const targetKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'] as const,propertyKeys=['multiLine','maxLen','textAlignment','fontSize','fontName'] as const
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)
export function validateEditFormTextPropertiesOperation(op:EditFormTextPropertiesOperation){
 if(!op||op.kind!=='editFormTextProperties'||Object.keys(op).some(k=>!['kind','sourceSha256',...targetKeys,...propertyKeys].includes(k))||!digest(op.sourceSha256)||!digest(op.widgetIdentity)||!digest(op.expectedWidgetSha256)||typeof op.fieldName!=='string'||!op.fieldName||op.fieldName.length>256||typeof op.widgetId!=='string'||!/^\d+R\d*$/.test(op.widgetId)||!propertyKeys.some(k=>op[k]!==undefined)||op.multiLine!==undefined&&typeof op.multiLine!=='boolean'||op.maxLen!==undefined&&(!Number.isInteger(op.maxLen)||op.maxLen<0||op.maxLen>4000)||op.fontSize!==undefined&&(typeof op.fontSize!=='number'||!Number.isFinite(op.fontSize)||op.fontSize<6||op.fontSize>72)||op.textAlignment!==undefined&&!['left','center','right'].includes(op.textAlignment)||op.fontName!==undefined&&!designTextFontNames.includes(op.fontName))throw Error('pdf_form_text_properties_invalid')
}
export async function formTextPropertiesAvailability(content:Uint8Array){const source=await formDesignCreateAvailability(content),available=source.createFormField&&(await inspectDesignWidgets(content)).widgets.some(w=>w.textPropertiesEditable);return {editFormTextProperties:available,editFormTextPropertiesReason:available?null:source.createFormFieldReason||'没有通过字体、身份与保护复核的独立文本控件'}}
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
function objectHash(object:unknown){return object instanceof PDFRawStream?hash(Buffer.concat([Buffer.from(object.dict.toString()),Buffer.from(object.contents)])):hash(String(object))}
function unchangedDict(dict:PDFDict,omit:string[]){return dict.entries().filter(([key])=>!omit.includes(String(key))).map(([key,value])=>[String(key),String(value)])}
export async function editDesignTextProperties(content:Uint8Array,expectedSha256:string,op:EditFormTextPropertiesOperation){
 validSource(content,expectedSha256,op.sourceSha256);validateEditFormTextPropertiesOperation(op)
 const availability=await formDesignCreateAvailability(content);if(!availability.createFormField)throw Error(availability.createFormFieldReason||'pdf_form_text_properties_source_unsupported')
 const matches=(await inspectDesignWidgets(content)).widgets.filter(w=>w.textPropertiesEditable&&targetKeys.every(k=>w[k]===op[k]));if(matches.length!==1)throw Error('pdf_form_text_properties_stale_or_readonly')
 const d=await PDFDocument.load(content,{updateMetadata:false}),field=d.getForm().getField(op.fieldName),support=inspectDesignTextProperties(field)
 if(!(field instanceof PDFTextField)||!support.editable||!support.properties)throw Error(support.reason||'pdf_form_text_properties_unsupported')
 const props=support.properties,value=field.getText()??'',widget=field.acroField.getWidgets()[0],widgetRef=d.context.getObjectRef(widget.dict)!
 if(op.maxLen!==undefined&&op.maxLen!==0&&op.maxLen<value.length)throw Error('pdf_form_text_properties_max_length_below_current_value: 新上限小于现值长度，拒绝截断')
 const except=new Set([String(field.ref),String(widgetRef)]),preserved=d.context.enumerateIndirectObjects().filter(([ref])=>!except.has(String(ref))).map(([ref,object])=>[ref,objectHash(object)]as const),body=bodySnapshot(d),annotations=annotationsSnapshot(d),invariant=unchangedDict(field.acroField.dict,['/Ff','/MaxLen','/Q','/DA']),widgetInvariant=unchangedDict(widget.dict,['/AP'])
 if(op.multiLine!==undefined){if(op.multiLine)field.enableMultiline();else field.disableMultiline()}
 if(op.maxLen!==undefined)field.setMaxLength(op.maxLen===0?undefined:op.maxLen)
 if(op.textAlignment!==undefined)field.setAlignment((['left','center','right']as const).indexOf(op.textAlignment))
 if(op.fontSize!==undefined)field.setFontSize(op.fontSize)
 const fontName=op.fontName??props.fontName,font=await d.embedFont(fontName as StandardFonts);font.encodeText(value.replace(/[\r\n]/g,''));field.updateAppearances(font)
 const expectedField=field.acroField.dict.toString(),bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{const out=await PDFDocument.load(bytes,{updateMetadata:false}),f=out.getForm().getTextField(op.fieldName),w=f.acroField.getWidgets()[0],after=inspectDesignTextProperties(f)
  if(!formDesignTreeSafe(out)||!after.editable||!after.properties||String(f.ref)!==String(field.ref)||String(out.context.getObjectRef(w.dict))!==String(widgetRef)||f.getText()!==value||f.acroField.dict.toString()!==expectedField||JSON.stringify(unchangedDict(f.acroField.dict,['/Ff','/MaxLen','/Q','/DA']))!==JSON.stringify(invariant)||JSON.stringify(unchangedDict(w.dict,['/AP']))!==JSON.stringify(widgetInvariant)||JSON.stringify(bodySnapshot(out))!==JSON.stringify(body)||JSON.stringify(annotationsSnapshot(out))!==JSON.stringify(annotations)||preserved.some(([ref,sha])=>objectHash(out.context.lookup(ref))!==sha)||after.properties.fontName!==fontName||op.multiLine!==undefined&&f.isMultiline()!==op.multiLine||op.maxLen!==undefined&&f.getMaxLength()!==(op.maxLen===0?undefined:op.maxLen)||op.textAlignment!==undefined&&after.properties.textAlignment!==op.textAlignment||op.fontSize!==undefined&&after.properties.fontSize!==op.fontSize)throw Error('text values, field/widget identity, appearances or original objects changed')
 }catch(error){reason='pdf_form_text_properties_output_review_failed: '+String(error)}
 const reviewIssues:Array<{operationIndex:number;kind:string;code:string;fieldName:string;message:string;details?:unknown}>=[]
 try{const issue=await inspectFormTextOverflow(await PDFDocument.load(bytes,{updateMetadata:false}),op.fieldName);if(issue)reviewIssues.push({operationIndex:0,kind:op.kind,...issue})}catch(error){reviewIssues.push({operationIndex:0,kind:op.kind,code:'pdf_form_text_overflow_review_failed',fieldName:op.fieldName,message:'字段“'+op.fieldName+'”的文字裁切风险复核失败；实际生成文件已保留，请人工核对：'+String(error)})}
 const result=receipt(content,bytes,op,reason)
 return {...result,reviewIssues,previewDigest:hash(JSON.stringify({previewDigest:result.previewDigest,reviewIssues}))}
}
