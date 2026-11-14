import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {inspectTextObjects,loadPdfium} from '../src/main/text-edit'
async function fixture(){const doc=await PDFDocument.create();doc.addPage([500,500]).drawText('Original target',{x:60,y:350,size:14});doc.addPage([500,500]).drawText('Control text',{x:60,y:350,size:14});return doc.save()}
async function ops(bytes:Uint8Array){const m=await inspectPdf(bytes,true),target=m.pages[0]!.textObjects![0]!;return [
 {kind:'insertText',sourceSha256:m.sourceSha256,pageId:m.pages[1]!.pageId,text:'New on second page',origin:[60,200],fontSize:12,color:[0,0,0],align:'left',font:'times'},
 {kind:'replaceText',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'Updated target',font:'courier',fontSize:12},
 {kind:'insertText',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,text:'New on first page',origin:[60,200],fontSize:12,color:[0,0,0],align:'left'},
 ]}
test('mixed replacements and inserts keep original interleaved indices pages text and deterministic digest',async()=>{
 const bytes=await fixture(),operations=await ops(bytes),snapshot=JSON.stringify(operations),result=await patchPdfWithReceipt(bytes,operations,sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0,1,2]);assert.deepEqual(result.skippedOperations,[]);assert.equal(result.sourceSha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes));assert.equal(JSON.stringify(operations),snapshot)
 const texts=(await inspectTextObjects(result.bytes)).map(page=>page.map(item=>item.text));assert.deepEqual(texts,[['Updated target','New on first page'],['Control text','New on second page']])
 assert.equal((await patchPdfWithReceipt(bytes,operations,sha256(bytes))).previewDigest,result.previewDigest)
 assert.notEqual((await patchPdfWithReceipt(bytes,[...operations].reverse(),sha256(bytes))).previewDigest,result.previewDigest)
})
test('mixed insertion origins and all original source hashes are checked before the first writer',async()=>{
 const bytes=await fixture(),operations=await ops(bytes),pdfium=await loadPdfium(),save=pdfium._PDFiumExt_SaveAsCopy;let writes=0
 try{pdfium._PDFiumExt_SaveAsCopy=(...args)=>{writes++;return save(...args)}
  for(const patch of [{sourceSha256:'0'.repeat(64)},{pageId:'forged'},{origin:[-1,0]}])await assert.rejects(patchPdfWithReceipt(bytes,[operations[1],operations[0],{...operations[2],...patch}],sha256(bytes)))
  await assert.rejects(patchPdfWithReceipt(bytes,[operations[0],{...operations[1],sourceSha256:'0'.repeat(64)}],sha256(bytes)))
  assert.equal(writes,0)
 }finally{pdfium._PDFiumExt_SaveAsCopy=save}
})
test('a stale replacement retains valid inserts and reports its original index only',async()=>{
 const bytes=await fixture(),operations=await ops(bytes);operations[1]={...operations[1],objectId:'stale'}
 const result=await patchPdfWithReceipt(bytes,operations,sha256(bytes));assert.deepEqual(result.appliedOperationIndices,[0,2]);assert.deepEqual(result.skippedOperations.map(skip=>skip.operationIndex),[1]);assert.match(result.skippedOperations[0]!.reason,/identity/)
 const text=(await inspectTextObjects(result.bytes)).flat().map(item=>item.text).join('|');assert.match(text,/Original target/);assert.match(text,/New on first page/);assert.match(text,/New on second page/)
})
test('mixed text rejects unrelated operation families rather than silently discarding them',async()=>{
 const bytes=await fixture(),operations=await ops(bytes)
 for(const extra of [{kind:'rotatePage',pageId:operations[0]!.pageId,delta:90},{kind:'addMarkup',pageId:operations[0]!.pageId,markupType:'underline',quads:[[60,320,130,320,60,300,130,300]],color:[1,0,0]}])await assert.rejects(patchPdfWithReceipt(bytes,[...operations,extra],sha256(bytes)))
})
test('an intermediate insertion load failure retains real replaced bytes and original skip indices',async(t)=>{
 const bytes=await fixture(),operations=await ops(bytes),expected=await patchPdfWithReceipt(bytes,[operations[1]],sha256(bytes)),load=PDFDocument.load
 t.mock.method(PDFDocument,'load',async function(content:Parameters<typeof PDFDocument.load>[0],...args:Parameters<typeof PDFDocument.load> extends [unknown,...infer Rest]?Rest:never){if(content instanceof Uint8Array&&sha256(content)===expected.sha256)throw Error('injected insert load failure');return load.call(PDFDocument,content,...args)})
 const result=await patchPdfWithReceipt(bytes,operations,sha256(bytes));assert.deepEqual(result.bytes,expected.bytes);assert.deepEqual(result.appliedOperationIndices,[1]);assert.deepEqual(result.skippedOperations.map(skip=>[skip.operationIndex,skip.pageId]),[[0,operations[0]!.pageId],[2,operations[2]!.pageId]]);assert.ok(result.skippedOperations.every(skip=>skip.reason.includes('injected insert load failure')))
})
test('plain source-bound replacements preserve normal object identity when mixed with insertion',async()=>{
 const bytes=await fixture(),operations=await ops(bytes),{font,fontSize,sourceSha256,...plain}=operations[1]!
 const result=await patchPdfWithReceipt(bytes,[operations[0],plain],sha256(bytes));assert.deepEqual(result.appliedOperationIndices,[0,1]);assert.deepEqual(result.skippedOperations,[])
 assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text==='Updated target'))
})
