import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,degrees} from 'pdf-lib'
import {inspectExistingImages,transformExistingImage} from './existing-image'
import {listExistingEngineImages} from './existing-image-engine'
import {inspectTextObjects} from '../src/main/text-edit'
import {sha256,patchPdfWithReceipt} from './operations'
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==','base64')
async function fixture(rotation=0){const d=await PDFDocument.create(),p=d.addPage([400,500]),q=d.addPage([400,500]),image=await d.embedPng(png);p.setCropBox(10,20,380,460);p.setRotation(degrees(rotation));p.drawText('Original body',{x:30,y:450});p.drawImage(image,{x:60,y:90,width:100,height:80});p.drawImage(image,{x:240,y:300,width:80,height:60});q.drawImage(image,{x:40,y:40,width:60,height:60});return d.save()}
async function operation(bytes:Uint8Array){const m=await inspectExistingImages(bytes),w=m.existingImages[0]!;return {kind:'transformExistingImage',sourceSha256:sha256(bytes),pageId:w.pageId,imageId:w.imageId,expectedImageSha256:w.expectedImageSha256,rect:w.rect,remove:true}}
test('deletes one shared-pixel page image placement at every page rotation without changing survivors or text',async()=>{
 for(const rotation of [0,90,180,270]){const bytes=await fixture(rotation),m=await inspectExistingImages(bytes);assert.equal(m.existingImages[0]!.removable,true);assert.equal(m.existingImages[0]!.replaceable,false)
  const original=await listExistingEngineImages(bytes),text=await inspectTextObjects(bytes),result=await patchPdfWithReceipt(bytes,[await operation(bytes)],sha256(bytes)),after=await listExistingEngineImages(result.bytes)
  assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(after.map(w=>({page:w.pageIndex,rect:w.rect,pixels:w.pixelsSha256})),original.slice(1).map(w=>({page:w.pageIndex,rect:w.rect,pixels:w.pixelsSha256})));assert.deepEqual(await inspectTextObjects(result.bytes),text)
  const out=await PDFDocument.load(result.bytes);assert.equal(out.getPageCount(),2);assert.equal(out.getPage(0).getRotation().angle,rotation);assert.deepEqual(out.getPage(0).getCropBox(),{x:10,y:20,width:380,height:460});assert.equal(result.sourceSha256,sha256(bytes))
 }
})
test('image removal rejects stale identities mixed geometry pixel operations and multiple operations',async()=>{
 const bytes=await fixture(),op=await operation(bytes)
 for(const patch of [{remove:false},{image:png.toString('base64')},{bake:{kind:'flip',axis:'h'}},{rect:[80,90,180,170]},{expectedImageSha256:'0'.repeat(64)},{imageId:'0'.repeat(64)},{sourceSha256:'0'.repeat(64)}])await assert.rejects(transformExistingImage(bytes,{...op,...patch},sha256(bytes)))
 await assert.rejects(patchPdfWithReceipt(bytes,[op,op],sha256(bytes)))
})
test('template images and static fill metadata do not advertise independent image removal',async()=>{
 const base=await PDFDocument.create(),p=base.addPage([200,200]),img=await base.embedPng(png);p.drawImage(img,{x:30,y:30,width:100,height:100});const d=await PDFDocument.create(),page=d.addPage([400,500]),[embedded]=await d.embedPdf(await base.save(),[0]);page.drawPage(embedded!,{x:20,y:30,width:200,height:200});const template=await d.save();const m=await inspectExistingImages(template);assert.equal(m.existingImages[0]!.editable,true);assert.equal(m.existingImages[0]!.removable,false);await assert.rejects(transformExistingImage(template,await operation(template),sha256(template)))
 const filled=await PDFDocument.load(await fixture());filled.catalog.set(PDFName.of('GenOfficeStaticFormFills'),filled.context.obj('opaque'));const bytes=await filled.save();assert.ok((await inspectExistingImages(bytes)).existingImages.every(w=>!w.removable));await assert.rejects(transformExistingImage(bytes,await operation(bytes),sha256(bytes)))
})
test('image delete output-review failures retain real bytes with only the selected placement removed',async(t)=>{
 const bytes=await fixture(),op=await operation(bytes),load=PDFDocument.load
 t.mock.method(PDFDocument,'load',async function(input:Parameters<typeof load>[0],options:Parameters<typeof load>[1]){if(input instanceof Uint8Array&&sha256(input)!==sha256(bytes))throw Error('injected image delete review');return load.call(PDFDocument,input,options)})
 const result=await transformExistingImage(bytes,op,sha256(bytes));t.mock.restoreAll();assert.notEqual(sha256(result.bytes),sha256(bytes));assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/output_review_failed.*injected image delete review/);assert.equal((await listExistingEngineImages(result.bytes)).length,2);assert.equal(result.sha256,sha256(result.bytes))
})
