/** Multiple source-bound creations reuse the pinned single-field writer without overwriting the source. */
import {inspectDesignWidgets} from './form-design'
import {resolveFormCopy} from './form-source-copy'
import {createHash} from 'node:crypto'
import {PDFDocument} from 'pdf-lib'
import {createDesignField,validateDesignCreation,designRectPage,formDesignCreateAvailability,type CreateFormFieldOperation} from './form-design-create'
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
export async function createDesignFields(content:Uint8Array,operations:CreateFormFieldOperation[],expectedSha256:string){
 if(operations.length===1)return createDesignField(content,expectedSha256,operations[0]!)
 const sourceSha256=hash(content)
 if(!operations.length||operations.length>500||sourceSha256!==expectedSha256||operations.some(op=>op.sourceSha256!==sourceSha256))throw Error('pdf_form_create_batch_source_invalid')
 operations.forEach(validateDesignCreation)
 const document=await PDFDocument.load(content,{updateMetadata:false}),availability=await formDesignCreateAvailability(content)
 if(!availability.createFormField)throw Error(availability.createFormFieldReason!)
 const widgets=operations.some(op=>op.copyFrom)?(await inspectDesignWidgets(content)).widgets:[]
 const names=document.getForm().getFields().map(field=>field.getName())
 const targets=operations.map(op=>{
  if(names.some(name=>name===op.fieldName||name.startsWith(op.fieldName+'.')||op.fieldName.startsWith(name+'.')))throw Error('pdf_form_create_duplicate_or_prefix_name')
  if(op.copyFrom)resolveFormCopy(document,widgets,op)
  names.push(op.fieldName)
  return {page:designRectPage(document,sourceSha256,op.pageId,op.rect),radio:op.radioWidgets?.map(widget=>designRectPage(document,sourceSha256,widget.pageId,widget.rect))}
 })
 let bytes=content
 const appliedOperationIndices:number[]=[],skippedOperations:{operationIndex:number;kind:'createFormField';pageId:string;fieldName:string;reason:string}[]=[]
 for(const [index,op]of operations.entries()){
  const currentSha256=hash(bytes),target=targets[index]!,pageId=`sha256:${currentSha256}:page:${target.page}`
  const rebound={...op,sourceSha256:currentSha256,pageId,...(op.radioWidgets?{radioWidgets:op.radioWidgets.map((widget,row)=>({...widget,pageId:`sha256:${currentSha256}:page:${target.radio![row]}`}))}:{})}
  try{
   if(op.copyFrom){const current=(await inspectDesignWidgets(bytes)).widgets.find(w=>w.widgetId===op.copyFrom!.widgetId&&w.fieldName===op.copyFrom!.fieldName&&w.expectedWidgetSha256===op.copyFrom!.expectedWidgetSha256);if(!current)throw Error('pdf_form_copy_original_widget_changed');rebound.copyFrom={fieldName:current.fieldName,widgetId:current.widgetId,widgetIdentity:current.widgetIdentity,expectedWidgetSha256:current.expectedWidgetSha256}}
   const result=await createDesignField(bytes,currentSha256,rebound);bytes=result.bytes
   if(result.appliedOperationIndices.includes(0))appliedOperationIndices.push(index)
   skippedOperations.push(...result.skippedOperations.map(skip=>({operationIndex:index,kind:'createFormField' as const,pageId:op.pageId,fieldName:op.fieldName,reason:skip.reason})))
  }catch(error){skippedOperations.push({operationIndex:index,kind:'createFormField',pageId:op.pageId,fieldName:op.fieldName,reason:`pdf_form_create_failed: ${error instanceof Error?error.message:String(error)}`})}
 }
 const outputSha256=hash(bytes)
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operations,outputSha256,appliedOperationIndices,skippedOperations}))}
}
