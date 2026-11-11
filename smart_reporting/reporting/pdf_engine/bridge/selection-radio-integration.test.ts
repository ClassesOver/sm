import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'

test('public operation accepts selection style runs and rejects foreign run keys',async()=>{
 const document=await PDFDocument.create(),page=document.addPage([300,400]);page.drawText('Original',{x:30,y:300,size:14})
 const bytes=await document.save(),model=await inspectPdf(bytes,true),target=model.pages[0]!.textObjects![0]!
 const operation={kind:'replaceText',sourceSha256:sha256(bytes),pageId:model.pages[0]!.pageId,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'Mixed text',styleRuns:[{start:0,end:5,bold:true}]}
 const result=await patchPdfWithReceipt(bytes,[operation],sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 await assert.rejects(patchPdfWithReceipt(bytes,[{...operation,styleRuns:[{start:0,end:5,script:true}]}],sha256(bytes)))
})

test('public operation appends a radio widget and advertises exact availability',async()=>{
 const document=await PDFDocument.create(),page=document.addPage([300,400]),group=document.getForm().createRadioGroup('answer')
 group.addOptionToPage('Yes',page,{x:30,y:200,width:20,height:20});group.select('Yes')
 const bytes=await document.save(),model=await inspectPdf(bytes),widget=model.formDesignWidgets[0]!
 assert.equal(model.capabilities.appendRadioWidget,true)
 const operation={kind:'appendRadioWidget',sourceSha256:sha256(bytes),fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256,pageId:model.pages[0]!.pageId,rect:[80,200,100,220],exportValue:'No'}
 const result=await patchPdfWithReceipt(bytes,[operation],sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 const output=(await PDFDocument.load(result.bytes)).getForm().getRadioGroup('answer')
 assert.deepEqual(output.getOptions(),['Yes','No']);assert.equal(output.getSelected(),'Yes')
 await assert.rejects(patchPdfWithReceipt(bytes,[operation,operation],sha256(bytes)),/单独保存/)
})
