import assert from 'node:assert/strict'
import { test } from 'node:test'
import { writeFile, mkdir } from 'node:fs/promises'
import { PDFDocument, PDFArray, PDFDict, PDFName, PDFString } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'
import { applyAttachments } from '../src/main/pdf-attachments'
import { decodeAttachmentPayload } from './attachments'
const add = (name: string, data = 'hello') => ({kind:'addAttachment',name,bytesBase64:Buffer.from(data).toString('base64')})
async function fixture() {
 const doc=await PDFDocument.create();doc.addPage([300,400]);doc.getForm().createTextField('title').setText('original')
 applyAttachments(doc,{add:[{name:'source-key',bytesBase64:Buffer.from('original-file').toString('base64'),description:'preserve'}]})
 const names=doc.catalog.lookup(PDFName.of('Names'),PDFDict),array=names.lookup(PDFName.of('EmbeddedFiles'),PDFDict).lookup(PDFName.of('Names'),PDFArray)
 array.set(0,PDFString.of('source-key'));const spec=doc.context.lookup(array.get(1),PDFDict);spec.set(PDFName.of('F'),PDFString.of('same.txt'));spec.set(PDFName.of('UF'),PDFString.of('same.txt'))
 names.set(PDFName.of('Dests'),doc.context.obj({Names:[]}));return doc.save({useObjectStreams:false})
}
test('real add/remove, name-tree identity, byte sorting, deterministic receipt and preservation',async()=>{
 const source=await fixture(),model=await inspectPdf(source);assert.equal(model.attachmentsEditable,true);assert.equal(model.attachments[0].name,'same.txt')
 const operations=[add('a.txt'),add('空.txt',''),{kind:'rotatePage',pageId:model.pages[0].pageId,delta:90}]
 const result=await patchPdfWithReceipt(source,operations,model.sourceSha256),again=await patchPdfWithReceipt(source,operations,model.sourceSha256)
 assert.equal(result.sha256,again.sha256);assert.equal(result.previewDigest,again.previewDigest)
 const after=await inspectPdf(result.bytes);assert.equal(after.attachments.length,3);assert.equal(after.attachments[0].key,'source-key');assert.equal(after.attachments[0].expectedAttachmentSha256,model.attachments[0].expectedAttachmentSha256);assert.equal(after.formFields[0].value,'original');assert.equal(after.pages[0].rotation,90)
 const doc=await PDFDocument.load(result.bytes),names=doc.catalog.lookup(PDFName.of('Names'),PDFDict),array=names.lookup(PDFName.of('EmbeddedFiles'),PDFDict).lookup(PDFName.of('Names'),PDFArray)
 assert.ok(names.has(PDFName.of('Dests')));const raw=Array.from({length:array.size()/2},(_,i)=>Buffer.from((array.get(i*2) as PDFString).asBytes()));assert.deepEqual(raw,[...raw].sort(Buffer.compare))
 const row=model.attachments[0],remove={kind:'removeAttachment',attachmentId:row.attachmentId,expectedAttachmentSha256:row.expectedAttachmentSha256}
 const replaced=await patchPdfWithReceipt(source,[remove,add('source-key','replacement')],model.sourceSha256);assert.equal((await inspectPdf(replaced.bytes)).attachments[0].size,11)
 const empty=await patchPdfWithReceipt(source,[remove],model.sourceSha256);assert.equal((await inspectPdf(empty.bytes)).attachments.length,0)
 await mkdir('/workspace/scratch/pr196-attachment-write',{recursive:true});for(const [name,bytes] of [['source',source],['output',result.bytes],['removed',empty.bytes]] as const)await writeFile(`/workspace/scratch/pr196-attachment-write/${name}.pdf`,bytes)
})
test('stale identities, collisions, malformed encoding and bounded payloads are rejected',async()=>{
 const source=await fixture(),model=await inspectPdf(source),row=model.attachments[0]
 for(const ops of [[add('source-key')],[add('../unsafe')],[{...add('x'),bytesBase64:'a==='}],[{...add('x'),unexpected:1}],[{kind:'removeAttachment',attachmentId:row.attachmentId,expectedAttachmentSha256:'0'.repeat(64)}],[{kind:'removeAttachment',attachmentId:row.attachmentId,expectedAttachmentSha256:row.expectedAttachmentSha256},{kind:'removeAttachment',attachmentId:row.attachmentId,expectedAttachmentSha256:row.expectedAttachmentSha256}],[{...add('x'),sourceSha256:'0'.repeat(64)}]])await assert.rejects(()=>patchPdfWithReceipt(source,ops,model.sourceSha256))
 assert.throws(()=>decodeAttachmentPayload(Buffer.alloc(2*1024*1024+1).toString('base64')));assert.throws(()=>decodeAttachmentPayload('Zh=='))
 await assert.rejects(()=>patchPdfWithReceipt(source,[0,1,2,3].map(i=>({...add(String(i)),bytesBase64:Buffer.alloc(2*1024*1024).toString('base64')})),model.sourceSha256),/total_limit/)
})
test('hierarchical, shared and protected sources stay read-only',async()=>{
 for(const mode of ['kids','shared','protected','linked']){
 const doc=await PDFDocument.load(await fixture()),tree=doc.catalog.lookup(PDFName.of('Names'),PDFDict).lookup(PDFName.of('EmbeddedFiles'),PDFDict),array=tree.lookup(PDFName.of('Names'),PDFArray)
 if(mode==='kids')tree.set(PDFName.of('Kids'),doc.context.obj([]));if(mode==='shared')doc.catalog.set(PDFName.of('Other'),array.get(1));if(mode==='protected')doc.catalog.set(PDFName.of('Perms'),doc.context.obj({}));if(mode==='linked')doc.catalog.set(PDFName.of('AF'),doc.context.obj([]))
 const source=await doc.save(),model=await inspectPdf(source);assert.equal(model.attachmentsEditable,false,mode);await assert.rejects(()=>patchPdfWithReceipt(source,[add('new')],model.sourceSha256),/readonly/)
 }
})
test('empty source and mixed form/note writes retain content',async()=>{
 const doc=await PDFDocument.create();doc.addPage([300,400]);doc.getForm().createTextField('title').setText('old');const source=await doc.save(),model=await inspectPdf(source),field=model.formFields[0]
 const result=await patchPdfWithReceipt(source,[add('new.txt'),{kind:'setFormValue',name:field.name,fieldKind:'text',fieldId:field.fieldId,expectedFieldSha256:field.expectedFieldSha256,value:'new'},{kind:'addTextAnnotation',pageId:model.pages[0].pageId,rect:[10,10,40,40],text:'note'}],model.sourceSha256)
 const after=await inspectPdf(result.bytes);assert.equal(after.attachments[0].size,5);assert.equal(after.formFields[0].value,'new');assert.equal(after.pages[0].notes[0].contents,'note')
})
test('same display basenames retain independent deletion identities',async()=>{
 const doc=await PDFDocument.load(await fixture());applyAttachments(doc,{add:[{name:'another-key',bytesBase64:Buffer.from('second').toString('base64')}]})
 const array=doc.catalog.lookup(PDFName.of('Names'),PDFDict).lookup(PDFName.of('EmbeddedFiles'),PDFDict).lookup(PDFName.of('Names'),PDFArray)
 for(let i=1;i<array.size();i+=2){const spec=doc.context.lookup(array.get(i),PDFDict);spec.set(PDFName.of('UF'),PDFString.of('same.txt'))}
 const source=await doc.save(),model=await inspectPdf(source);assert.equal(model.attachments.length,2)
 const row=model.attachments.find(row=>row.key==='source-key')!,result=await patchPdfWithReceipt(source,[{kind:'removeAttachment',attachmentId:row.attachmentId,expectedAttachmentSha256:row.expectedAttachmentSha256}],model.sourceSha256)
 const after=await inspectPdf(result.bytes);assert.equal(after.attachments.length,1);assert.equal(after.attachments[0].key,'another-key');assert.equal(after.attachments[0].size,6)
})
test('malformed keys, direct specs, shared streams, unsupported filters and raw signatures are readonly',async()=>{
 for(const mode of ['duplicate','direct','stream','filter','signature']){
 const doc=await PDFDocument.load(await fixture()),tree=doc.catalog.lookup(PDFName.of('Names'),PDFDict).lookup(PDFName.of('EmbeddedFiles'),PDFDict),array=tree.lookup(PDFName.of('Names'),PDFArray),spec=doc.context.lookup(array.get(1),PDFDict),ef=spec.lookup(PDFName.of('EF'),PDFDict)
 if(mode==='duplicate'){array.push(array.get(0));array.push(array.get(1))}
 if(mode==='direct')array.set(1,spec)
 if(mode==='stream')doc.catalog.set(PDFName.of('Other'),ef.get(PDFName.of('F'))!)
 if(mode==='filter')(doc.context.lookup(ef.get(PDFName.of('F'))) as any).dict.set(PDFName.of('Filter'),PDFName.of('LZWDecode'))
 if(mode==='signature')doc.catalog.set(PDFName.of('Other'),doc.context.obj({Type:'Sig',ByteRange:[0,1,2,3]}))
 const source=await doc.save(),model=await inspectPdf(source);assert.equal(model.attachmentsEditable,false,mode);await assert.rejects(()=>patchPdfWithReceipt(source,[add('new')],model.sourceSha256),/readonly/)
 }
})
test('Flate source files are preserved and decompression is bounded',async()=>{
 for(const large of [false,true]){
 const doc=await PDFDocument.load(await fixture()),array=doc.catalog.lookup(PDFName.of('Names'),PDFDict).lookup(PDFName.of('EmbeddedFiles'),PDFDict).lookup(PDFName.of('Names'),PDFArray),spec=doc.context.lookup(array.get(1),PDFDict),streamRef=spec.lookup(PDFName.of('EF'),PDFDict).get(PDFName.of('F'))!
 const content=large?Buffer.alloc(8*1024*1024+1):Buffer.from('compressed original')
 doc.context.assign(streamRef as any,doc.context.flateStream(content,{Type:'EmbeddedFile',Params:{Size:content.length}}))
 const source=await doc.save(),model=await inspectPdf(source);assert.equal(model.attachmentsEditable,!large)
 if(large)await assert.rejects(()=>patchPdfWithReceipt(source,[add('new')],model.sourceSha256),/readonly/)
 else {assert.equal(model.attachments[0].size,content.length);const output=await patchPdfWithReceipt(source,[add('new')],model.sourceSha256);assert.equal((await inspectPdf(output.bytes)).attachments.find(row=>row.key==='source-key')!.expectedAttachmentSha256,model.attachments[0].expectedAttachmentSha256)}
 }
})
