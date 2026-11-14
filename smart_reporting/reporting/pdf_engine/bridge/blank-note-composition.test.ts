import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt} from './operations'

test('existing blank insertion and note composition uses an empty original annotation prefix for a new page',async()=>{
 const document=await PDFDocument.create();document.addPage([300,400]);const source=await document.save(),model=await inspectPdf(source),first=model.pages[0].pageId
 const operations=[{kind:'insertBlankPage',pageId:'blank:note-test',width:300,height:400},{kind:'addTextAnnotation',pageId:first,rect:[10,10,40,40],text:'Original page note'},{kind:'reorderPages',pageIds:['blank:note-test',first]}]
 const output=await patchPdfWithReceipt(source,operations,model.sourceSha256),after=await inspectPdf(output.bytes)
 assert.equal(after.pageCount,2);assert.deepEqual(after.pages[0].notes,[]);assert.equal(after.pages[1].notes[0].contents,'Original page note')
 assert.deepEqual(output.appliedOperationIndices,[0,1,2]);assert.deepEqual(output.skippedOperations,[])
})
