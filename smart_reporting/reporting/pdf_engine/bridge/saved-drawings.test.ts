import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFString } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'
import { markupDictionaryHash } from './markup-delete'
async function fixture() {
  const doc = await PDFDocument.create(); const page = doc.addPage([400,500]); page.drawText('surviving source text')
  const field = doc.getForm().createTextField('survivor'); field.setText('original'); field.addToPage(page,{x:10,y:450,width:100,height:20})
  const note = doc.context.register(doc.context.obj({Type:'Annot',Subtype:'Text',Rect:[200,100,220,118],Contents:PDFString.of('surviving note')})); page.node.addAnnot(note)
  const bytes = await doc.save(), model = await inspectPdf(bytes), pageId = model.pages[0]!.pageId
  return (await patchPdfWithReceipt(bytes,[
    ...['arrow','arrow','rect','ellipse','ink','polygon','caret'].map(shape=>({kind:'addDrawing',pageId,shape,color:[1,0,0],width:2,...(shape==='arrow'?{from:[20,30],to:[120,90]}:shape==='ink'?{paths:[[30,300,60,330,90,310]]}:shape==='polygon'?{vertices:[[20,20],[120,40],[80,140]]}:shape==='caret'?{point:[200,300]}:{rect:[20,30,120,90]})})),
  ],model.sourceSha256)).bytes
}
function remove(page: Awaited<ReturnType<typeof inspectPdf>>['pages'][number], index=1) {
  const drawing=page.drawings[index]!;return {kind:'removeDrawing',pageId:page.pageId,annotationId:drawing.annotationId,expectedAnnotationSha256:drawing.expectedAnnotationSha256}
}
async function hashes(bytes:Uint8Array) { const doc=await PDFDocument.load(bytes); const a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);return a.asArray().map(raw=>({ref:String(raw),hash:markupDictionaryHash(doc.context.lookup(raw,PDFDict))})) }
test('saved drawing exact slot removal preserves identical twin, all other annotations, form and text resources',async()=>{
 const bytes=await fixture(),before=Buffer.from(bytes),model=await inspectPdf(bytes),page=model.pages[0]!
 assert.equal(model.capabilities.removeDrawing,true);assert.equal(page.drawings.length,7);assert.ok(page.drawings.every(d=>d.removable),JSON.stringify(page.drawings))
 assert.deepEqual(page.drawings[0]!.rect,page.drawings[1]!.rect);assert.notEqual(page.drawings[0]!.annotationId,page.drawings[1]!.annotationId)
 const operation=remove(page), originals=await hashes(bytes),result=await patchPdfWithReceipt(bytes,[operation],model.sourceSha256)
 const reopened=await inspectPdf(result.bytes)
 assert.equal(reopened.pages[0]!.drawings.length,6);assert.equal(reopened.pages[0]!.notes.length,page.notes.length)
 assert.deepEqual(await hashes(result.bytes),originals.filter((_,i)=>i!==page.drawings[1]!.annotationIndex))
 assert.deepEqual(reopened.formFields.map(({fieldId,...field})=>field),model.formFields.map(({fieldId,...field})=>field));assert.deepEqual(Buffer.from(bytes),before)
 const b=await PDFDocument.load(bytes),a=await PDFDocument.load(result.bytes)
 for(const key of ['Contents','Resources']) assert.equal(String(a.getPage(0).node.get(PDFName.of(key))),String(b.getPage(0).node.get(PDFName.of(key))))
 await assert.rejects(patchPdfWithReceipt(result.bytes,[operation],reopened.sourceSha256))
 for(const ops of [[{...operation,expectedAnnotationSha256:'0'.repeat(64)}],[{...operation,annotationId:'0'.repeat(64)}],[operation,operation],[{...operation,subtype:'Line'}],[operation,{kind:'cropPage',pageId:page.pageId,rect:[0,0,300,400]}]]) await assert.rejects(patchPdfWithReceipt(bytes,ops,model.sourceSha256))
})
test('relationships, shared appearances, locked flags, direct annotations and protected sources remain visible readonly',async()=>{
 for(const mode of ['relation','incoming','sharedAP','locked','direct','protected']) {
  const doc=await PDFDocument.load(await fixture()),page=doc.getPage(0),annots=page.node.lookup(PDFName.of('Annots'),PDFArray),first=annots.lookup(2,PDFDict),second=annots.lookup(3,PDFDict)
  if(mode==='relation') first.set(PDFName.of('Popup'),annots.get(3))
  if(mode==='incoming') doc.catalog.set(PDFName.of('UnrecognizedReference'),annots.get(2))
  if(mode==='sharedAP') second.set(PDFName.of('AP'),first.get(PDFName.of('AP'))!)
  if(mode==='locked') first.set(PDFName.of('F'),doc.context.obj(128))
  if(mode==='direct') annots.set(2,first)
  if(mode==='protected') doc.catalog.set(PDFName.of('Perms'),doc.context.obj({DocMDP:PDFString.of('protected')}))
  const bytes=await doc.save(),model=await inspectPdf(bytes),drawing=model.pages[0]!.drawings[0]!
  if(mode==='protected') assert.equal(model.capabilities.removeDrawing,false)
  assert.equal(drawing.removable,false,mode);assert.ok(drawing.removalReason,mode)
  await assert.rejects(patchPdfWithReceipt(bytes,[remove(model.pages[0]!,0)],model.sourceSha256),undefined,mode)
 }
})
test('every supported drawing subtype removes safely and exact source page survives rotate/reorder',async()=>{
 const source=await fixture(),doc=await PDFDocument.load(source);doc.addPage([200,300]);const bytes=await doc.save(),model=await inspectPdf(bytes),page=model.pages[0]!
 for(const index of [0,2,3,4,5,6]) {
  const result=await patchPdfWithReceipt(bytes,[remove(page,index)],model.sourceSha256)
  assert.equal((await inspectPdf(result.bytes)).pages[0]!.drawings.length,6)
 }
 const result=await patchPdfWithReceipt(bytes,[{kind:'reorderPages',pageIds:[model.pages[1]!.pageId,page.pageId]},remove(page),{kind:'rotatePage',pageId:page.pageId,delta:90}],model.sourceSha256)
 const reopened=await inspectPdf(result.bytes)
 assert.equal(reopened.pages[0]!.drawings.length,0);assert.equal(reopened.pages[1]!.drawings.length,6);assert.equal(reopened.pages[1]!.rotation,90)
})
