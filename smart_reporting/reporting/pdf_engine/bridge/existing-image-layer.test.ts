import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,degrees} from 'pdf-lib'
import {inspectExistingImages,transformExistingImage} from './existing-image'
import {listExistingEngineImages} from './existing-image-engine'
import {inspectTextObjects} from '../src/main/text-edit'
import {sha256,patchPdfWithReceipt} from './operations'
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==','base64')
async function fixture(above=true,rotation=0,text=true){const d=await PDFDocument.create(),p=d.addPage([400,500]),q=d.addPage([400,500]),image=await d.embedPng(png);p.setCropBox(10,20,380,460);p.setRotation(degrees(rotation));const draw=()=>p.drawImage(image,{x:40,y:300,width:200,height:50});if(!above)draw();if(text){p.drawText('Original body',{x:30,y:450});p.drawText('COVERED CONTROL',{x:50,y:320,size:20})}if(above)draw();p.drawImage(image,{x:260,y:80,width:50,height:50});q.drawImage(image,{x:40,y:40,width:60,height:60});return d.save()}
async function operation(bytes:Uint8Array,layer='belowText'){const m=await inspectExistingImages(bytes),w=m.existingImages.find(w=>w.pageIndex===0&&w.rect[0]===40)!;return {kind:'transformExistingImage',sourceSha256:sha256(bytes),pageId:w.pageId,imageId:w.imageId,expectedImageSha256:w.expectedImageSha256,rect:w.rect,layer}}
test('switches image text bands in both directions at every page rotation retaining pixels geometry and all other content',async()=>{
 for(const above of [true,false])for(const rotation of [0,90,180,270]){
  const bytes=await fixture(above,rotation),m=await inspectExistingImages(bytes),target=m.existingImages.find(w=>w.rect[0]===40&&w.pageIndex===0)!;assert.equal(target.layerable,true);assert.equal(target.aboveText,above)
  const original=await listExistingEngineImages(bytes),oldText=await inspectTextObjects(bytes),result=await patchPdfWithReceipt(bytes,[await operation(bytes,above?'belowText':'aboveText')],sha256(bytes)),after=await listExistingEngineImages(result.bytes),changed=after.find(w=>w.pageIndex===0&&w.rect[0]===40)!
  assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[]);assert.equal(changed.aboveText,!above);assert.deepEqual(changed.rect,target.rect);assert.equal(changed.pixelsSha256,original.find(w=>w.pageIndex===0&&w.rect[0]===40)!.pixelsSha256)
  const rest=(rows:typeof original)=>rows.filter(w=>!(w.pageIndex===0&&w.rect[0]===40)).map(w=>({page:w.pageIndex,rect:w.rect,pixels:w.pixelsSha256,above:w.aboveText}));assert.deepEqual(rest(after),rest(original));assert.deepEqual(await inspectTextObjects(result.bytes),oldText.map((runs,pageIndex)=>runs.map(run=>{if(pageIndex!==0)return run;assert.equal(run.objectPath?.length,1);return {...run,objectPath:[run.objectPath![0]!+(above?1:-1)]}})))
  const out=await PDFDocument.load(result.bytes);assert.equal(out.getPage(0).getRotation().angle,rotation);assert.deepEqual(out.getPage(0).getCropBox(),{x:10,y:20,width:380,height:460})
 }
})
test('layer edits reject same band stale identity or simultaneous geometry pixel replacement and deletion',async()=>{
 const bytes=await fixture(),op=await operation(bytes)
 for(const patch of [{layer:'aboveText'},{layer:'front'},{rect:[41,300,241,350]},{remove:true},{image:png.toString('base64')},{bake:{kind:'flip',axis:'h'}},{expectedImageSha256:'0'.repeat(64)}])await assert.rejects(transformExistingImage(bytes,{...op,...patch},sha256(bytes)))
})
test('pages without text or with static-fill metadata do not expose image text-layer changes',async()=>{
 const noText=await fixture(true,0,false);assert.ok((await inspectExistingImages(noText)).existingImages.every(w=>!w.layerable));await assert.rejects(transformExistingImage(noText,await operation(noText),sha256(noText)))
 const d=await PDFDocument.load(await fixture());d.catalog.set(PDFName.of('GenOfficeStaticFormFills'),d.context.obj('opaque'));const bytes=await d.save();assert.ok((await inspectExistingImages(bytes)).existingImages.every(w=>!w.layerable));await assert.rejects(transformExistingImage(bytes,await operation(bytes),sha256(bytes)))
})
test('image layer output-review fault retains actual reordered bytes and specific warning',async(t)=>{
 const bytes=await fixture(),op=await operation(bytes),load=PDFDocument.load;t.mock.method(PDFDocument,'load',async function(input:Parameters<typeof load>[0],options:Parameters<typeof load>[1]){if(input instanceof Uint8Array&&sha256(input)!==sha256(bytes))throw Error('injected image layer review');return load.call(PDFDocument,input,options)})
 const result=await transformExistingImage(bytes,op,sha256(bytes));t.mock.restoreAll();assert.match(result.skippedOperations[0]!.reason,/output_review_failed.*injected image layer review/);assert.equal((await listExistingEngineImages(result.bytes)).find(w=>w.pageIndex===0&&w.rect[0]===40)!.aboveText,false)
})
test('a page containing Form objects does not expose layer changes even for its direct image',async()=>{
 const template=await PDFDocument.create();template.addPage([100,100]).drawText('Template text');const d=await PDFDocument.load(await fixture()),[embedded]=await d.embedPdf(await template.save(),[0]);d.getPage(0).drawPage(embedded!,{x:10,y:30,width:100,height:100});const bytes=await d.save();assert.ok((await inspectExistingImages(bytes)).existingImages.filter(w=>w.pageIndex===0).every(w=>!w.layerable));await assert.rejects(transformExistingImage(bytes,await operation(bytes),sha256(bytes)))
})
test('keeps the own rotated image matrix when only its text band changes',async()=>{
 const d=await PDFDocument.create(),p=d.addPage([400,500]),image=await d.embedPng(png);p.drawText('Original rotation control',{x:30,y:450});p.drawImage(image,{x:100,y:200,width:100,height:80,rotate:degrees(30)});const bytes=await d.save(),w=(await inspectExistingImages(bytes)).existingImages[0]!
 const {chainPdfium,loadPdfium,withDocument}=await import('../src/main/text-edit')
 const matrix=(content:Uint8Array)=>chainPdfium(async()=>{const m=await loadPdfium();return withDocument(m,content,async doc=>{const page=m._FPDF_LoadPage(doc,0),buffer=m._malloc(24);try{for(let i=0;i<m._FPDFPage_CountObjects(page);i++){const object=m._FPDFPage_GetObject(page,i);if(m._FPDFPageObj_GetType(object)===3){assert.ok(m._FPDFPageObj_GetMatrix(object,buffer));return Array.from(m.HEAPF32.subarray(buffer>>2,(buffer>>2)+6))}}throw Error('image matrix missing')}finally{m._free(buffer);m._FPDF_ClosePage(page)}})})
 const original=await matrix(bytes),result=await transformExistingImage(bytes,{kind:'transformExistingImage',sourceSha256:sha256(bytes),pageId:w.pageId,imageId:w.imageId,expectedImageSha256:w.expectedImageSha256,rect:w.rect,layer:'belowText'},sha256(bytes)),changed=await matrix(result.bytes)
 assert.deepEqual(result.skippedOperations,[]);assert.ok(Math.abs(original[1]!)>1);assert.ok(changed.every((value,i)=>Math.abs(value-original[i]!)<1e-4));assert.equal((await listExistingEngineImages(result.bytes))[0]!.pixelsSha256,(await listExistingEngineImages(bytes))[0]!.pixelsSha256)
})
