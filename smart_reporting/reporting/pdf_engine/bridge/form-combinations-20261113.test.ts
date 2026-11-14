import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {mkdir,writeFile} from 'node:fs/promises'
import {PDFDocument,PDFName} from 'pdf-lib'
import {inspectDesignWidgets,removeDesignWidgetWithReceipt} from './form-design'
import {createDesignField,type CreateFormFieldOperation} from './form-design-create'
import {editDesignWidget,formDesignPropertiesAvailability,type FormWidgetTarget,type EditFormWidgetOperation} from './form-design-properties'
import {applySaveRequest} from '../src/main/save-pdf'
import {stagePdfFormWidgetProperties,type PdfFormCreateModel} from '../../../report_editor/frontend/src/pdf-form-create'
import {stagePdfFormWidgetRemoval} from '../../../report_editor/frontend/src/pdf-form-design'
const sha=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex')
const directory=process.env.PDF_FORM_COMBINATIONS_EVIDENCE??'/dev/shm/office-ui-combinations-20261113/pdf'
const target=(w:FormWidgetTarget):FormWidgetTarget=>({fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256})
async function model(bytes:Uint8Array){
 const d=await PDFDocument.load(bytes,{updateMetadata:false}),census=await inspectDesignWidgets(bytes)
 return {sourceSha256:sha(bytes),formDesignWidgets:census.widgets,capabilities:{...await formDesignPropertiesAvailability(bytes),removeFormWidget:census.widgets.some(w=>w.removable||w.radioRemovalEditable)},pages:d.getPages().map((p,index)=>({index,pageId:'sha256:'+sha(bytes)+':page:'+index,cropBox:p.getCropBox(),rotation:p.getRotation().angle}))}
}
async function fixture(){
 const d=await PDFDocument.create();d.setCreationDate(new Date(0));d.setModificationDate(new Date(0))
 const pages=[d.addPage([400,500]),d.addPage([400,500])]
 pages.forEach((p,i)=>p.drawText('Unchanged page '+i,{x:20,y:455}))
 let bytes=await d.save({useObjectStreams:false})
 // 使用真实创建入口，避免 pdf-lib 直接新建层级字段遗留孤立 Parent 别名。
 for(const kind of ['radio','choice','text']as const){
  const h=sha(bytes),pageId=(index:number)=>'sha256:'+h+':page:'+index
  const op:CreateFormFieldOperation={kind:'createFormField',sourceSha256:h,pageId:pageId(kind==='choice'?1:0),fieldName:'party.'+({radio:'answer',choice:'choice',text:'code'}[kind]),fieldKind:kind,rect:kind==='radio'?[40,300,60,320]:kind==='choice'?[40,230,180,255]:[40,180,160,205],required:false,...(kind==='radio'?{radioWidgets:['Yes','No','Maybe'].map((exportValue,i)=>({pageId:pageId(i%2),rect:[40+i*65,300,60+i*65,320]as [number,number,number,number],exportValue,checked:i===0}))}:kind==='choice'?{options:['One','Two'],value:'Two'}:{value:'C001'})}
  const result=await createDesignField(bytes,h,op);assert.deepEqual(result.skippedOperations,[]);bytes=result.bytes
 }
 return bytes
}
async function saveStage(label:string,bytes:Uint8Array,operation:unknown,receipt:unknown){
 await mkdir(directory,{recursive:true});await writeFile(directory+'/'+label+'.pdf',bytes)
 await writeFile(directory+'/'+label+'.json',JSON.stringify({sha256:sha(bytes),operation,receipt},null,2))
}
test('cross-page radio and choice survive sequential properties, values, middle-widget removal and later edits',async()=>{
 let bytes=await fixture();await saveStage('00-source',bytes,null,null)
 const original=await model(bytes),originalIds=original.formDesignWidgets.map(w=>w.widgetId)
 async function edit(label:string,name:string,index:number,properties:Parameters<typeof stagePdfFormWidgetProperties>[3]){
  const m=await model(bytes),w=m.formDesignWidgets.filter(w=>w.fieldName===name)[index]
  const op=stagePdfFormWidgetProperties(m as PdfFormCreateModel,[],target(w),properties)[0] as unknown as EditFormWidgetOperation
  const result=await editDesignWidget(bytes,sha(bytes),op);await saveStage(label,result.bytes,op,{appliedOperationIndices:result.appliedOperationIndices,skippedOperations:result.skippedOperations})
  assert.deepEqual(result.skippedOperations,[],label);assert.deepEqual(result.appliedOperationIndices,[0],label);bytes=result.bytes
 }
 await edit('01-required','party.answer',1,{required:true})
 await edit('02-options','party.choice',0,{choiceOptions:['Three','Two','One']})
 await edit('03-geometry','party.answer',1,{rect:[110,290,138,318]})
 async function fill(label:string,radio:string,choice:string){
  const request={path:'',markups:[],drawings:[],stamps:[],formValues:[{name:'party.answer',kind:'radio' as const,value:radio},{name:'party.choice',kind:'choice' as const,value:choice}]}
  const result=await applySaveRequest(bytes,request);await saveStage(label,result.bytes,request,result.skippedTextEdits);bytes=result.bytes
  const doc=await PDFDocument.load(bytes,{updateMetadata:false});assert.equal(doc.getForm().getRadioGroup('party.answer').getSelected(),radio);assert.deepEqual(doc.getForm().getDropdown('party.choice').getSelected(),[choice])
 }
 await fill('04-filled','Maybe','Three')
 const beforeRemoval=bytes,m=await model(bytes),removed=m.formDesignWidgets.filter(w=>w.fieldName==='party.answer')[1]
 assert.equal(removed.pageIndex,1);assert.equal(removed.radioRemovalEditable,true)
 // 混批拒绝且不改草稿；撤销只需丢弃本次独立删除操作。
 const pending=[{kind:'setFormValue',name:'party.choice'}];assert.throws(()=>stagePdfFormWidgetRemoval(m,pending,removed.widgetIdentity),/单独保存/);assert.deepEqual(pending,[{kind:'setFormValue',name:'party.choice'}])
 const removal=stagePdfFormWidgetRemoval(m,[],removed.widgetIdentity)[0]
 const result=await removeDesignWidgetWithReceipt(bytes,sha(bytes),target(removed));await saveStage('05-removed',result.bytes,removal,{appliedOperationIndices:result.appliedOperationIndices,skippedOperations:result.skippedOperations});assert.deepEqual(result.skippedOperations,[]);bytes=result.bytes
 const after=await model(bytes);assert.deepEqual(after.formDesignWidgets.map(w=>w.widgetId),originalIds.filter(id=>id!==removed.widgetId));assert.equal(after.formDesignWidgets.filter(w=>w.fieldName==='party.answer').length,2)
 const f=(await PDFDocument.load(bytes,{updateMetadata:false})).getForm().getRadioGroup('party.answer');assert.deepEqual(f.acroField.getOnValues().map(String),['/0','/2']);assert.equal(f.getSelected(),'Maybe');assert.equal(f.isRequired(),true)
 await assert.rejects(removeDesignWidgetWithReceipt(bytes,sha(bytes),target(removed)))
 // 此处仅检查删除前字节仍独立存在，不声称模拟 NativeDraft 的持久化撤销。
 assert.equal((await model(beforeRemoval)).formDesignWidgets.filter(w=>w.fieldName==='party.answer').length,3)
 await edit('06-survivor-geometry','party.answer',1,{rect:[165,290,193,318]})
 await fill('07-filled-yes','Yes','One');await fill('08-filled-maybe','Maybe','Three')
 const out=await PDFDocument.load(bytes,{updateMetadata:false});assert.equal(out.getForm().getTextField('party.code').getText(),'C001');assert.equal(out.getForm().getRadioGroup('party.answer').isRequired(),true)
 assert.deepEqual(out.getForm().getRadioGroup('party.answer').acroField.getWidgets().map(w=>String(w.dict.get(PDFName.of('AS')))),['/Off','/2'])
 await writeFile(directory+'/source-stage-model.json',JSON.stringify(original,null,2));await writeFile(directory+'/final-stage-model.json',JSON.stringify(await model(bytes),null,2))
})
