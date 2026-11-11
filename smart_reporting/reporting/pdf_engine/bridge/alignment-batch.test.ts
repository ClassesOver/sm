import assert from 'node:assert/strict'
import test from 'node:test'
import {PDFDocument,StandardFonts} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
async function fixture(text:string){const d=await PDFDocument.create(),f=await d.embedFont(StandardFonts.Helvetica);d.addPage([300,400]).drawText(text,{x:30,y:350,size:12,font:f});return d.save()}
test('unified bridge accepts a source-bound real form creation and returns its actual preview model',async()=>{
 const bytes=await fixture('source'),source=await inspectPdf(bytes)
 assert.equal(source.capabilities.createFormField,true)
 const op={kind:'createFormField',sourceSha256:source.sourceSha256,pageId:source.pages[0].pageId,fieldName:'new_field',fieldKind:'text',rect:[40,100,240,130],required:true}
 const result=await patchPdfWithReceipt(bytes,[op],source.sourceSha256)
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 const output=await inspectPdf(result.bytes);assert.equal(output.formFields[0].name,'new_field')
 await assert.rejects(()=>patchPdfWithReceipt(bytes,[op,{kind:'rotatePage',pageId:source.pages[0].pageId,delta:90}],source.sourceSha256))
})
test('unified bridge inserts externally identified real pages rather than blank pages',async()=>{
 const bytes=await fixture('parent'),foreign=await fixture('foreign'),sourceSha256=sha256(bytes)
 const result=await patchPdfWithReceipt(bytes,[{kind:'externalPages',action:'insert',sourceSha256,externalSha256:sha256(foreign),bytesBase64:Buffer.from(foreign).toString('base64'),afterPageIndex:0}],sourceSha256)
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 assert.equal((await inspectPdf(result.bytes)).pageCount,2)
})
