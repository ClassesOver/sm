/** Source-bound deep copies retain V/DV/fonts/AP without reconstructing browser projections. */
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFObjectCopier,PDFRef,PDFSignature,PDFStream,PDFString} from 'pdf-lib'
import {radioCopyMatches,type RadioCopyRow} from './form-copy-radio'
import {inspectDesignWidgets,formDesignTreeSafe,type DesignWidgetIdentity} from './form-design'
import {annotationsSnapshot,bodySnapshot,fieldSnapshot,formDesignCreateAvailability,designRectPage,receipt,validSource,validateDesignCreation,type CreateFormFieldOperation} from './form-design-create'
export type FormCopySource=Pick<DesignWidgetIdentity,'fieldName'|'widgetId'|'widgetIdentity'|'expectedWidgetSha256'>
const identityKeys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'] as const
export function resolveFormCopy(document:PDFDocument,widgets:DesignWidgetIdentity[],op:CreateFormFieldOperation){
 const target=op.copyFrom
 if(!target||Object.keys(target).length!==4||Object.keys(target).some(k=>!identityKeys.includes(k as typeof identityKeys[number])))throw Error('pdf_form_copy_identity_invalid')
 const matches=widgets.filter(w=>w.copyEditable&&identityKeys.every(k=>w[k]===target[k]))
 if(matches.length!==1)throw Error('pdf_form_copy_source_invalid_or_unsupported')
 const source=matches[0]!,group=widgets.filter(w=>w.fieldName===source.fieldName),sameParent=(name:string)=>name.split('.').slice(0,-1).join('.')
 if(source.fieldKind!==op.fieldKind||source.required!==op.required||sameParent(source.fieldName)!==sameParent(op.fieldName))throw Error('pdf_form_copy_template_changed')
 if(op.fieldKind==='radio'){
  const rows:RadioCopyRow[]=group.map((w,i)=>({pageId:'sha256:'+op.sourceSha256+':page:'+w.pageIndex,rect:w.rect,exportValue:w.radioOptions?.[i]??'',checked:w.radioChecked===true}))
  if(group[0]!==source||group.some(w=>!w.copyEditable)||!op.radioWidgets||!radioCopyMatches(rows,op.radioWidgets,op.pageId,op.rect,document.getPages().map((_,i)=>'sha256:'+op.sourceSha256+':page:'+i)))throw Error('pdf_form_copy_radio_template_changed')
 }else if(group.length!==1||Math.abs(op.rect[2]-op.rect[0]-(source.rect[2]-source.rect[0]))>1e-7||Math.abs(op.rect[3]-op.rect[1]-(source.rect[3]-source.rect[1]))>1e-7)throw Error('pdf_form_copy_template_changed')
 return {source,field:document.getForm().getField(source.fieldName),group}
}
function graph(document:PDFDocument){return document.context.enumerateIndirectObjects().map(([ref,obj])=>{if(obj instanceof PDFStream){obj.updateDict();return [String(ref),obj.dict.toString(),Buffer.from(obj.getContents()).toString('base64')]}return [String(ref),String(obj)]})}
export async function copyDesignField(content:Uint8Array,expectedSha256:string,op:CreateFormFieldOperation){
 validSource(content,expectedSha256,op.sourceSha256);validateDesignCreation(op)
 const d=await PDFDocument.load(content,{updateMetadata:false}),availability=await formDesignCreateAvailability(content)
 if(!availability.createFormField)throw Error(availability.createFormFieldReason!)
 const widgets=(await inspectDesignWidgets(content)).widgets,{field}=resolveFormCopy(d,widgets,op),rows=op.fieldKind==='radio'?op.radioWidgets!:[{pageId:op.pageId,rect:op.rect}],indices=rows.map(row=>designRectPage(d,expectedSha256,row.pageId,row.rect))
 if(d.getForm().getFields().some(f=>f.getName()===op.fieldName||f.getName().startsWith(op.fieldName+'.')||op.fieldName.startsWith(f.getName()+'.')))throw Error('pdf_form_create_duplicate_or_prefix_name')
 const originalFields=fieldSnapshot(d),body=bodySnapshot(d),annotations=annotationsSnapshot(d),context=d.context,copy=PDFObjectCopier.for(context,context)
 const merged=field instanceof PDFSignature&&field.acroField.getWidgets()[0]!.dict===field.acroField.dict
 const rawField=field.acroField.dict.clone(),parent=rawField.get(PDFName.of('Parent'))
 rawField.delete(PDFName.of('Parent'));rawField.delete(PDFName.of('Kids'));if(merged)rawField.delete(PDFName.of('P'))
 const newField=copy.copy(rawField),fieldRef=context.register(newField),widgetRefs=merged?[fieldRef]:field.acroField.getWidgets().map((widget,i)=>{
  const rawWidget=widget.dict.clone();rawWidget.delete(PDFName.of('Parent'));rawWidget.delete(PDFName.of('P'));const newWidget=copy.copy(rawWidget),ref=context.register(newWidget)
  newWidget.set(PDFName.of('Parent'),fieldRef);newWidget.set(PDFName.of('P'),d.getPage(indices[i]!).ref);newWidget.set(PDFName.of('Rect'),context.obj(rows[i]!.rect));return ref
 })
 newField.set(PDFName.of('T'),PDFString.of(op.fieldName.split('.').at(-1)!));if(merged){newField.set(PDFName.of('P'),d.getPage(indices[0]!).ref);newField.set(PDFName.of('Rect'),context.obj(rows[0]!.rect))}else newField.set(PDFName.of('Kids'),context.obj(widgetRefs))
 if(parent){if(!(parent instanceof PDFRef))throw Error('pdf_form_copy_parent_invalid');newField.set(PDFName.of('Parent'),parent)}
 const container=parent?context.lookup(parent,PDFDict):d.getForm().acroForm.dict,key=PDFName.of(parent?'Kids':'Fields'),list=container.lookup(key,PDFArray).clone();list.push(fieldRef);container.set(key,list)
 for(const[i,ref]of widgetRefs.entries()){const page=d.getPage(indices[i]!),annots=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.clone()??context.obj([]);annots.push(ref);page.node.set(PDFName.of('Annots'),annots)}
 const expectedFields=fieldSnapshot(d),expectedBody=bodySnapshot(d),expectedAnnotations=annotationsSnapshot(d),expectedGraph=graph(d)
 const bytes=await d.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{
  const out=await PDFDocument.load(bytes,{updateMetadata:false}),outFields=fieldSnapshot(out),outBody=bodySnapshot(out),outAnnotations=annotationsSnapshot(out)
  if(!formDesignTreeSafe(out)||JSON.stringify(outFields)!==JSON.stringify(expectedFields)||JSON.stringify(outBody)!==JSON.stringify(expectedBody)||JSON.stringify(outAnnotations)!==JSON.stringify(expectedAnnotations)||JSON.stringify(graph(out))!==JSON.stringify(expectedGraph)||JSON.stringify(outBody)!==JSON.stringify(body)||JSON.stringify(fieldSnapshot(out,op.fieldName))!==JSON.stringify(originalFields)||JSON.stringify(annotationsSnapshot(out,widgetRefs))!==JSON.stringify(annotations))throw Error('copied field or original graph changed')
  const matches=(await inspectDesignWidgets(bytes)).widgets.filter(w=>w.fieldName===op.fieldName);if(matches.length!==rows.length||matches.some((w,i)=>!w.copyEditable||w.pageIndex!==indices[i]||JSON.stringify(w.rect)!==JSON.stringify(rows[i]!.rect)))throw Error('copy identity or geometry not preserved')
 }catch(error){reason='pdf_form_copy_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}
