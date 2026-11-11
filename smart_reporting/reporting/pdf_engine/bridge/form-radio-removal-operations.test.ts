import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'

async function fixture(){
 const document=await PDFDocument.create(),page=document.addPage([300,400]),field=document.getForm().createRadioGroup('answer')
 field.addOptionToPage('Yes',page,{x:30,y:200,width:20,height:20})
 field.addOptionToPage('No',page,{x:90,y:200,width:20,height:20});field.select('Yes')
 return document.save({useObjectStreams:false})
}
async function operation(bytes:Uint8Array){
 const model=await inspectPdf(bytes),widget=model.formDesignWidgets.find(w=>w.fieldName==='answer'&&(w as any).radioRemovalEditable)!
 assert.ok(widget)
 return {kind:'removeFormWidget',sourceSha256:model.sourceSha256,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256}
}
test('public radio removal capability permits only removal and preserves selected survivor',async()=>{
 const bytes=await fixture(),model=await inspectPdf(bytes)
 assert.equal(model.capabilities.removeFormWidget,true)
 assert.equal(model.capabilities.editFormFieldRequired,false)
 const op=await operation(bytes),result=await patchPdfWithReceipt(bytes,[op],sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 assert.equal(result.sha256,sha256(result.bytes));assert.equal(result.size,result.bytes.length)
 const document=await PDFDocument.load(result.bytes),field=document.getForm().getRadioGroup('answer')
 assert.equal(field.getSelected(),'Yes');assert.deepEqual(field.getOptions(),['Yes'])
 assert.equal(field.acroField.getWidgets().length,1)
 await assert.rejects(patchPdfWithReceipt(bytes,[op,op],sha256(bytes)))
})
test('public radio removal returns the actual bytes and failed review receipt after postwrite fault',async()=>{
 const bytes=await fixture(),op=await operation(bytes),load=PDFDocument.load
 try{
  PDFDocument.load=async(...args)=>{const document=await load.call(PDFDocument,...args);if(sha256(args[0] as Uint8Array)!==sha256(bytes))document.getForm=()=>{throw Error('injected public removal readback')};return document}
  const result=await patchPdfWithReceipt(bytes,[op],sha256(bytes))
  assert.equal(result.sha256,sha256(result.bytes));assert.deepEqual(result.appliedOperationIndices,[])
  assert.match(result.skippedOperations[0].reason,/output_review_failed.*injected public removal readback/)
  assert.equal((await load.call(PDFDocument,result.bytes)).getForm().getRadioGroup('answer').acroField.getWidgets().length,1)
 }finally{PDFDocument.load=load}
})
