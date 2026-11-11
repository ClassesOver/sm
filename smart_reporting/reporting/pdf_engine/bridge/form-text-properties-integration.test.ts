import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,TextAlignment} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'

test('public text properties operation keeps field value references and original body',async()=>{
 const document=await PDFDocument.create(),page=document.addPage([300,400]);page.drawText('unchanged body',{x:20,y:350})
 const field=document.getForm().createTextField('customer');field.setText('Alice');field.addToPage(page,{x:20,y:200,width:180,height:60})
 const bytes=await document.save(),model=await inspectPdf(bytes),widget=model.formDesignWidgets[0]!
 assert.equal(model.capabilities.editFormTextProperties,true);assert.equal(widget.textPropertiesEditable,true)
 const operation={kind:'editFormTextProperties',sourceSha256:sha256(bytes),fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256,multiLine:true,maxLen:50,textAlignment:'right',fontSize:18}
 const result=await patchPdfWithReceipt(bytes,[operation],sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 const output=(await PDFDocument.load(result.bytes)).getForm().getTextField('customer')
 assert.equal(output.getText(),'Alice');assert.equal(output.isMultiline(),true);assert.equal(output.getMaxLength(),50);assert.equal(output.getAlignment(),TextAlignment.Right)
 assert.equal(String(output.ref),String(field.ref));assert.equal(sha256(result.bytes),result.sha256)
 await assert.rejects(patchPdfWithReceipt(bytes,[{...operation,foreign:true}],sha256(bytes)))
 await assert.rejects(patchPdfWithReceipt(bytes,[operation,operation],sha256(bytes)),/单独保存/)
})
