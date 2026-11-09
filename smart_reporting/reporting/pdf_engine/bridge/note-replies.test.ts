import assert from 'node:assert/strict'
import { test } from 'node:test'
import { writeFile } from 'node:fs/promises'
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'
async function fixture() {
 const doc=await PDFDocument.create();doc.addPage([300,400]);doc.addPage([300,400]);doc.getForm().createTextField('control').setText('unchanged');const bytes=await doc.save(),model=await inspectPdf(bytes)
 return (await patchPdfWithReceipt(bytes,[{kind:'addTextAnnotation',pageId:model.pages[0].pageId,rect:[30,100,50,118],text:'root',createdMs:0},{kind:'addTextAnnotation',pageId:model.pages[0].pageId,rect:[30,100,50,118],text:'root',createdMs:0}],model.sourceSha256)).bytes
}
function op(model:Awaited<ReturnType<typeof inspectPdf>>,index=0){const note=model.pages[0].notes[index];return {kind:'replyNote',pageId:model.pages[0].pageId,annotationId:note.annotationId,expectedAnnotationSha256:note.expectedAnnotationSha256,contents:'回复 ✓',createdMs:1793970000123}}
test('exact duplicate-looking parent, repeated flat replies, actual IRT and deterministic output',async()=>{
 const source=await fixture(),model=await inspectPdf(source);assert.equal(model.pages[0].notes[1].replyable,true)
 const reply=op(model,1),result=await patchPdfWithReceipt(source,[reply],model.sourceSha256),again=await patchPdfWithReceipt(source,[reply],model.sourceSha256);assert.equal(result.sha256,again.sha256);assert.equal(result.previewDigest,again.previewDigest)
 const doc=await PDFDocument.load(result.bytes),annots=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(annots.size(),3)
 const child=annots.lookup(2,PDFDict);assert.equal(String(child.get(PDFName.of('IRT'))),String(annots.get(1)));assert.equal(String(child.get(PDFName.of('RT'))),'/R');assert.equal(child.lookup(PDFName.of('CreationDate')).decodeText(),'D:20261106130000Z')
 const updated=await inspectPdf(result.bytes);assert.equal(updated.pages[0].notes[1].replyable,true);assert.equal(updated.pages[0].notes[1].editable,false);assert.equal(updated.pages[0].notes[2].replyable,false)
 const more=await patchPdfWithReceipt(result.bytes,[op(updated,1)],updated.sourceSha256);assert.equal((await inspectPdf(more.bytes)).pages[0].notes.length,4)
 await writeFile('/workspace/scratch/pr196-replies/source.pdf',source);await writeFile('/workspace/scratch/pr196-replies/output.pdf',result.bytes)
})
test('stale/foreign identity, altered parent, delete/edit and geometry mixtures fail',async()=>{
 const source=await fixture(),model=await inspectPdf(source),reply=op(model)
 for(const operations of [[{...reply,expectedAnnotationSha256:'0'.repeat(64)}],[{...reply,pageId:model.pages[1].pageId}],[{...reply,unknown:1}],[{...reply,createdMs:-1}],[reply,{kind:'removeNote',pageId:reply.pageId,annotationId:reply.annotationId,expectedAnnotationSha256:reply.expectedAnnotationSha256}],[reply,{kind:'cropPage',pageId:reply.pageId,rect:[0,0,200,300]}],[reply,{kind:'deletePage',pageId:reply.pageId}]])await assert.rejects(()=>patchPdfWithReceipt(source,operations,model.sourceSha256))
})
test('protected, popup, nested, shared and cross-page parents remain readonly',async()=>{
 for(const mode of ['signature','popup','shared','nested','cross-page','locked','hidden','unknown-flags']){
 const doc=await PDFDocument.load(await fixture()),a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray),root=a.lookup(0,PDFDict)
 if(mode==='locked')root.set(PDFName.of('F'),PDFNumber.of(128))
 if(mode==='hidden')root.set(PDFName.of('F'),PDFNumber.of(32))
 if(mode==='unknown-flags')root.set(PDFName.of('F'),PDFNumber.of(2**32))
 if(mode==='signature')doc.catalog.set(PDFName.of('Other'),doc.context.obj({Type:'Sig',ByteRange:[0,1,2,3]}))
 if(mode==='popup')root.set(PDFName.of('Popup'),a.get(1))
 if(mode==='shared')doc.catalog.set(PDFName.of('Other'),a.get(0))
 if(mode==='nested'){const child=a.lookup(1,PDFDict);child.set(PDFName.of('IRT'),a.get(0));child.set(PDFName.of('RT'),PDFName.of('Group'))}
 if(mode==='cross-page')doc.getPage(1).node.set(PDFName.of('Annots'),doc.context.obj([a.get(0)]))
 const source=await doc.save(),model=await inspectPdf(source);assert.equal(model.pages[0].notes[0].replyable,false,mode);await assert.rejects(()=>patchPdfWithReceipt(source,[op(model)],model.sourceSha256))
 }
})
test('multiple replies survive reordering, rotation, unrelated note and form edits',async()=>{
 const source=await fixture(),model=await inspectPdf(source),field=model.formFields[0],reply=op(model),result=await patchPdfWithReceipt(source,[reply,{...reply,contents:'second'},{kind:'rotatePage',pageId:reply.pageId,delta:90},{kind:'reorderPages',pageIds:model.pages.map(p=>p.pageId).reverse()},{kind:'setFormValue',fieldId:field.fieldId,expectedFieldSha256:field.expectedFieldSha256,name:field.name,fieldKind:'text',value:'changed'}],model.sourceSha256)
 const doc=await PDFDocument.load(result.bytes),a=doc.getPage(1).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(a.size(),4);assert.equal(String(a.lookup(2,PDFDict).get(PDFName.of('IRT'))),String(a.get(0)));assert.equal(String(a.lookup(3,PDFDict).get(PDFName.of('IRT'))),String(a.get(0)));assert.equal(doc.getPage(1).getRotation().angle,90);assert.equal((await inspectPdf(result.bytes)).formFields[0].value,'changed')
})
test('independent post-write guard refuses upstream orphan fallback and a wrong identical-looking parent',async()=>{
 const {applySaveRequest}=await import('../src/main/save-pdf'),{normalizeAddedNoteDates}=await import('./note-timestamps')
 const source=await fixture(),doc=await PDFDocument.load(source),annots=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
 for(const missing of [true,false]){
 const result=await applySaveRequest(source,{path:'',markups:[],drawings:[{kind:'note',pageIndex:0,at:[30,118],color:[1,.85,0],contents:'orphan guard',createdMs:0,replyToSaved:{objNum:Number(String(annots.get(0)).split(' ')[0]),rect:[30,100,50,118],contents:missing?'not found':'root'}}],formValues:[],stamps:[],rotations:[],deletedPages:[]})
 await assert.rejects(()=>normalizeAddedNoteDates(source,result.bytes,[{pageIndex:0,contents:'orphan guard',rect:[30,100,50,118],createdMs:0,replyToRef:String(annots.get(1))}],[],[0,1]),/pdf_reply_parent_reference_changed/)
 if(missing){const out=await PDFDocument.load(result.bytes);assert.equal(out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).lookup(2,PDFDict).has(PDFName.of('IRT')),false);await writeFile('/workspace/scratch/pr196-replies/upstream-orphan-fallback.pdf',result.bytes)}
 }
})
