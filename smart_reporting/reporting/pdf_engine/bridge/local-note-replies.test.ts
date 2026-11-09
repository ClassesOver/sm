import assert from 'node:assert/strict'
import { test } from 'node:test'
import { writeFile, mkdir } from 'node:fs/promises'
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFHexString } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'
import { normalizeAddedNoteDates } from './note-timestamps'
const id='a'.repeat(32),other='b'.repeat(32)
async function fixture(){const doc=await PDFDocument.create();doc.addPage([300,400]);doc.addPage([300,400]);doc.getForm().createTextField('control').setText('unchanged');return doc.save()}
const root=(pageId:string,localId=id)=>({kind:'addTextAnnotation',pageId,localId,rect:[30,100,50,118],text:'identical root',createdMs:0})
const reply=(pageId:string,parentLocalId=id)=>({kind:'replyPendingNote',pageId,parentLocalId,contents:'local reply ✓',createdMs:1793970000123})
test('local-ID replies select identical roots, preserve unknown dates and ignore public operation order',async()=>{
 const source=await fixture(),m=await inspectPdf(source),page=m.pages[0].pageId
 const ops=[reply(page,other),root(page),{...root(page,other),createdMs:undefined}];delete ops[2].createdMs
 const result=await patchPdfWithReceipt(source,ops,m.sourceSha256),again=await patchPdfWithReceipt(source,ops,m.sourceSha256);assert.equal(result.sha256,again.sha256)
 const doc=await PDFDocument.load(result.bytes),a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(a.size(),3);assert.equal(String(a.lookup(2,PDFDict).get(PDFName.of('IRT'))),String(a.get(1)));assert.equal(a.lookup(1,PDFDict).has(PDFName.of('CreationDate')),false)
 assert.equal(a.lookup(2,PDFDict).lookup(PDFName.of('CreationDate')).decodeText(),'D:20261106130000Z');assert.equal((await inspectPdf(result.bytes)).pages[0].notes[1].replyable,true)
 const evidence=process.env.PDF_LOCAL_REPLY_EVIDENCE_DIR
 if(evidence){await mkdir(evidence,{recursive:true});await writeFile(`${evidence}/source.pdf`,source);await writeFile(`${evidence}/output.pdf`,result.bytes)}
})
test('missing/duplicate/cross-page/nested identities and protected sources refuse',async()=>{
 const source=await fixture(),m=await inspectPdf(source),page=m.pages[0].pageId
 for(const ops of [[reply(page)],[root(page),root(page),reply(page)],[root(page),reply(m.pages[1].pageId)],[root(page),{...reply(page),parentLocalId:'x'}],[root(page),{...reply(page),localId:other}],[root(page),reply(page),{kind:'cropPage',pageId:page,rect:[0,0,200,300]}],[root(page),reply(page),{kind:'deletePage',pageId:page}]])await assert.rejects(()=>patchPdfWithReceipt(source,ops,m.sourceSha256))
 const doc=await PDFDocument.load(source);doc.catalog.set(PDFName.of('Other'),doc.context.obj({Type:'Sig',ByteRange:[0,1,2,3]}));const protectedBytes=await doc.save(),pm=await inspectPdf(protectedBytes);assert.equal(pm.capabilities.pendingNoteReplies,false);await assert.rejects(()=>patchPdfWithReceipt(protectedBytes,[root(pm.pages[0].pageId),reply(pm.pages[0].pageId)],pm.sourceSha256),/source_readonly/)
})
test('multiple roots and children survive rotation/reorder plus unrelated note/form/attachment edits',async()=>{
 const source=await fixture(),m=await inspectPdf(source),page=m.pages[0].pageId,f=m.formFields[0]
 const ops=[root(page),root(m.pages[1].pageId,other),reply(page),reply(m.pages[1].pageId,other),{...reply(page),contents:'second child'},{kind:'rotatePage',pageId:page,delta:90},{kind:'reorderPages',pageIds:m.pages.map(p=>p.pageId).reverse()},{kind:'addTextAnnotation',pageId:page,rect:[80,100,100,118],text:'ordinary'},{kind:'setFormValue',fieldId:f.fieldId,expectedFieldSha256:f.expectedFieldSha256,name:f.name,fieldKind:'text',value:'changed'},{kind:'addAttachment',name:'control.bin',bytesBase64:'AP8='}]
 const result=await patchPdfWithReceipt(source,ops,m.sourceSha256),after=await inspectPdf(result.bytes);assert.equal(after.pages[1].notes.length,4);assert.equal(after.pages[0].notes.length,2);assert.equal(after.pages[1].rotation,90);assert.equal(after.formFields[0].value,'changed');assert.equal(after.attachments[0].size,2)
})
test('post-write verification refuses a reused old root reference, missing local parent and orphan fallback',async()=>{
 const doc=await PDFDocument.create(),page=doc.addPage([300,400]),ref=doc.context.register(doc.context.obj({Type:'Annot',Subtype:'Text',Rect:[30,100,50,118],Contents:PDFHexString.fromText('root')}));page.node.set(PDFName.of('Annots'),doc.context.obj([ref]));const base=await doc.save();page.node.set(PDFName.of('Annots'),doc.context.obj([ref,ref]));const duplicate=await doc.save()
 await assert.rejects(()=>normalizeAddedNoteDates(base,duplicate,[{pageIndex:0,rect:[30,100,50,118],contents:'root',localId:id}],[],[0]),/reference_reused/)
 const {applySaveRequest}=await import('../src/main/save-pdf'),empty=await fixture()
 const output=await applySaveRequest(empty,{path:'',markups:[],drawings:[{kind:'note',pageIndex:0,at:[30,118],contents:'identical root',color:[1,.85,0],createdMs:0,replyToLocalId:id}],formValues:[],stamps:[],rotations:[],deletedPages:[]})
 const orphan=await PDFDocument.load(output.bytes);assert.equal(orphan.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).lookup(0,PDFDict).has(PDFName.of('IRT')),false)
 await assert.rejects(()=>normalizeAddedNoteDates(empty,output.bytes,[{pageIndex:0,rect:[30,100,50,118],contents:'identical root',createdMs:0,replyToLocalId:id}],[],[0,1]),/parent_missing/)
})
