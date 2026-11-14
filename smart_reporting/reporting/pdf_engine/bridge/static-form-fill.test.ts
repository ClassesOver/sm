import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFArray,PDFDocument,PDFName,degrees} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {readStaticFormFills} from '../src/main/save-pdf'
import {listExistingEngineImages,renderExistingImageBgra} from './existing-image-engine'
const png='iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGElEQVR4nAXBAQEAAAjDIN7c5hNEciOlBz3iB3usnU7kAAAAAElFTkSuQmCC'
async function fixture(){const d=await PDFDocument.create();for(let i=0;i<3;i++)d.addPage([400,500]).drawText('Original '+i,{x:30,y:450});return d.save()}
async function fill(bytes:Uint8Array,index=0){const m=await inspectPdf(bytes);return {kind:'setStaticFill',sourceSha256:m.sourceSha256,pageId:m.pages[index]!.pageId,id:'fill-'+index,fillKind:'text',rect:[40,200,140,230],image:png,text:'中文填写',fontSize:14,color:'#111111',align:'left'}}
test('static filling writes actual content images and fixed metadata, then edits and removes the saved fill',async()=>{
 const source=await fixture(),op=await fill(source),r=await patchPdfWithReceipt(source,[op],sha256(source))
 assert.deepEqual(r.skippedOperations,[]);assert.deepEqual(r.appliedOperationIndices,[0]);assert.equal(r.sha256,sha256(r.bytes))
 const records=await readStaticFormFills(r.bytes);assert.equal(records[0]!.text,'中文填写');assert.equal((await listExistingEngineImages(r.bytes)).length,1)
 const d=await PDFDocument.load(r.bytes);assert.equal(d.getPage(0).node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.size()??0,0);assert.equal(d.getForm().getFields().length,0)
 const m=await inspectPdf(r.bytes),saved=m.staticFormFills[0]!
 assert.equal(saved.editable,true)
 const edited=await patchPdfWithReceipt(r.bytes,[{...op,sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,expectedImageSha256:saved.expectedImageSha256,text:'重新编辑',rect:[150,250,250,280]}],m.sourceSha256)
 assert.equal((await readStaticFormFills(edited.bytes))[0]!.text,'重新编辑');assert.equal((await listExistingEngineImages(edited.bytes)).length,1)
 const m2=await inspectPdf(edited.bytes),removed=await patchPdfWithReceipt(edited.bytes,[{kind:'removeStaticFill',sourceSha256:m2.sourceSha256,pageId:m2.pages[0]!.pageId,id:op.id,expectedImageSha256:m2.staticFormFills[0]!.expectedImageSha256}],m2.sourceSha256)
 assert.deepEqual(await readStaticFormFills(removed.bytes),[]);assert.equal((await listExistingEngineImages(removed.bytes)).length,0)
})
test('fixed writer remaps saved and new fills across page reorder and deletion without stale cache',async()=>{
 const source=await fixture(),m=await inspectPdf(source),ops=[await fill(source,0),await fill(source,2),{kind:'reorderPages',pageIds:[m.pages[2]!.pageId,m.pages[0]!.pageId]},{kind:'deletePage',pageId:m.pages[1]!.pageId}]
 const result=await patchPdfWithReceipt(source,ops,m.sourceSha256),records=await readStaticFormFills(result.bytes)
 assert.deepEqual(records.map(r=>[r.id,r.pageIndex]),[['fill-0',1],['fill-2',0]])
 const m2=await inspectPdf(result.bytes),next=await patchPdfWithReceipt(result.bytes,[{kind:'deletePage',pageId:m2.pages[0]!.pageId}],m2.sourceSha256)
 assert.deepEqual((await readStaticFormFills(next.bytes)).map(r=>[r.id,r.pageIndex]),[['fill-0',0]])
})
test('stale image fingerprints, forged pages, duplicate IDs and invalid PNG never mutate the source',async()=>{
 const source=await fixture(),op=await fill(source),r=await patchPdfWithReceipt(source,[op],sha256(source)),m=await inspectPdf(r.bytes)
 for(const patch of [{expectedImageSha256:'0'.repeat(64)},{pageId:m.pages[1]!.pageId},{image:'bad png'},{rect:[-1,0,30,30]},{text:''},{extra:true}])await assert.rejects(patchPdfWithReceipt(r.bytes,[{...op,sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,expectedImageSha256:m.staticFormFills[0]!.expectedImageSha256,...patch}],m.sourceSha256))
 await assert.rejects(patchPdfWithReceipt(source,[op,op],sha256(source)))
 assert.equal(sha256(source),op.sourceSha256)
})
test('static content insertion remains upright on all right-angle page rotations',async()=>{
 for(const angle of [0,90,180,270]){const d=await PDFDocument.load(await fixture());d.getPage(0).setRotation(degrees(angle));const source=await d.save(),op=await fill(source),r=await patchPdfWithReceipt(source,[op],sha256(source));assert.deepEqual(r.skippedOperations,[]);assert.deepEqual((await listExistingEngineImages(r.bytes))[0]!.rect,op.rect)}
})
test('static-fill output review faults retain generated content and warn instead of discarding bytes',async()=>{
 const source=await fixture(),op=await fill(source),load=PDFDocument.load
 try{
  PDFDocument.load=async(...args)=>{const d=await load.call(PDFDocument,...args);if(d.catalog.has(PDFName.of('GenOfficeStaticFormFills')))throw Error('injected static metadata readback failure');return d}
  const r=await patchPdfWithReceipt(source,[op],sha256(source));assert.equal(r.sha256,sha256(r.bytes));assert.deepEqual(r.appliedOperationIndices,[0]);assert.deepEqual(r.skippedOperations,[]);assert.ok(r.reviewIssues.some(issue=>issue.code==='pdf_static_fill_output_review_failed'))
  PDFDocument.load=load;assert.equal((await listExistingEngineImages(r.bytes)).length,1);assert.equal((await readStaticFormFills(r.bytes))[0]!.text,'中文填写')
 }finally{PDFDocument.load=load}
})
test('metadata serialization failure after content generation retains actual PDF bytes as a soft review issue',async()=>{
 const source=await fixture(),op=await fill(source),save=PDFDocument.prototype.save
 try{
  PDFDocument.prototype.save=async function(...args){if(this.catalog.has(PDFName.of('GenOfficeStaticFormFills')))throw Error('injected static metadata serialization failure');return save.apply(this,args)}
  const r=await patchPdfWithReceipt(source,[op],sha256(source));assert.equal(r.sha256,sha256(r.bytes));assert.equal((await listExistingEngineImages(r.bytes)).length,1);assert.ok(r.reviewIssues.some(issue=>issue.code==='pdf_static_fill_metadata_write_failed'))
 }finally{PDFDocument.prototype.save=save}
})
test('redaction drops the static-fill plain-text cache as well as the painted image',async()=>{
 const source=await fixture(),op=await fill(source),first=await patchPdfWithReceipt(source,[op],sha256(source)),model=await inspectPdf(first.bytes)
 const result=await patchPdfWithReceipt(first.bytes,[{kind:'redact',pageId:model.pages[0]!.pageId,rect:op.rect}],model.sourceSha256)
 assert.deepEqual(await readStaticFormFills(result.bytes),[])
 const before=(await listExistingEngineImages(first.bytes))[0]!,after=(await listExistingEngineImages(result.bytes))[0]!
 assert.notEqual(after.pixelsSha256,before.pixelsSha256)
 const cleared=await renderExistingImageBgra(result.bytes,0,op.rect as [number,number,number,number])
 assert.ok(cleared.bgra.every(channel=>channel===255),'redacted image pixels must be uniformly white')
 assert.equal(Buffer.from(result.bytes).includes(Buffer.from('中文填写')),false)
})
