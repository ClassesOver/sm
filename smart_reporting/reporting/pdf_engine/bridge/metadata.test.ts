import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,PDFString} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt} from './operations'
const modifiedMs=Date.UTC(2026,10,13,6,7,8)
const values={title:'合同 <更新> 中文',author:'Alice & 张三',subject:'',keywords:' alpha， beta; 中文；gamma, '}
async function source(){const doc=await PDFDocument.create();doc.addPage([300,400]).drawText('Original metadata body',{x:30,y:250});doc.setTitle('Original title');doc.setAuthor('Original author');doc.setSubject('Original subject');doc.setKeywords(['old']);doc.setProducer('Preserved producer');doc.setCreator('Preserved creator');doc.setCreationDate(new Date('2020-01-02T03:04:05Z'));doc.setModificationDate(new Date('2021-01-02T03:04:05Z'));doc.getInfoDict().set(PDFName.of('CustomAudit'),PDFString.of('Preserved custom'));return doc.save()}
test('metadata writes all four source fields, supports clearing and source keyword separators, and preserves unrelated properties',async()=>{
 const bytes=await source(),model=await inspectPdf(bytes),operation={kind:'setMetadata',sourceSha256:model.sourceSha256,modifiedMs,metadata:values}
 const result=await patchPdfWithReceipt(bytes,[operation,{kind:'rotatePage',pageId:model.pages[0].pageId,delta:90},{kind:'addTextAnnotation',pageId:model.pages[0].pageId,rect:[40,40,60,58],text:'New note',createdMs:0}],model.sourceSha256)
 const doc=await PDFDocument.load(result.bytes,{updateMetadata:false})
 assert.equal(doc.getTitle(),values.title);assert.equal(doc.getAuthor(),values.author);assert.equal(doc.getSubject(),'');assert.equal(doc.getKeywords(),'alpha beta 中文 gamma');assert.equal(doc.getModificationDate()?.getTime(),modifiedMs)
 assert.equal(doc.getProducer(),'Preserved producer');assert.equal(doc.getCreator(),'Preserved creator');assert.equal(doc.getCreationDate()?.toISOString(),'2020-01-02T03:04:05.000Z');assert.equal(doc.getInfoDict().lookup(PDFName.of('CustomAudit'),PDFString).decodeText(),'Preserved custom')
 assert.equal(doc.getPage(0).getRotation().angle,90);assert.equal((await inspectPdf(result.bytes)).pages[0].notes[0].contents,'New note');assert.deepEqual(result.appliedOperationIndices,[0,1,2]);assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.reviewIssues,[])
})
test('metadata preview identity remains deterministic across separate executions and no-op saves preserve original properties',async()=>{
 const bytes=await source(),model=await inspectPdf(bytes),op={kind:'setMetadata',sourceSha256:model.sourceSha256,modifiedMs,metadata:{title:'',author:'',subject:'',keywords:''}}
 const one=await patchPdfWithReceipt(bytes,[op],model.sourceSha256);await new Promise(r=>setTimeout(r,1100));const two=await patchPdfWithReceipt(bytes,[op],model.sourceSha256)
 assert.equal(one.sha256,two.sha256);assert.equal(one.previewDigest,two.previewDigest)
 const output=await PDFDocument.load(one.bytes,{updateMetadata:false});assert.deepEqual([output.getTitle(),output.getAuthor(),output.getSubject(),output.getKeywords()],['','','',''])
 const unchanged=await PDFDocument.load((await patchPdfWithReceipt(bytes,[{kind:'rotatePage',pageId:model.pages[0].pageId,delta:90}],model.sourceSha256)).bytes,{updateMetadata:false});assert.equal(unchanged.getTitle(),'Original title');assert.equal(unchanged.getModificationDate()?.toISOString(),'2021-01-02T03:04:05.000Z')
})
test('metadata rejects foreign identity, unsupported fields, invalid values and duplicate snapshots before writing',async()=>{
 const bytes=await source(),model=await inspectPdf(bytes),op={kind:'setMetadata',sourceSha256:model.sourceSha256,modifiedMs,metadata:values}
 for(const bad of [{...op,sourceSha256:'f'.repeat(64)},{...op,metadata:{...values,producer:'forged'}},{...op,metadata:{...values,title:4}},{...op,metadata:{...values,author:'x'.repeat(4097)}},{...op,metadata:{...values,subject:'a\0b'}},{...op,modifiedMs:-1}])await assert.rejects(patchPdfWithReceipt(bytes,[bad],model.sourceSha256))
 await assert.rejects(patchPdfWithReceipt(bytes,[op,op],model.sourceSha256))
})
test('metadata capability refuses signed or protected source',async()=>{
 const doc=await PDFDocument.load(await source(),{updateMetadata:false});doc.catalog.set(PDFName.of('Perms'),doc.context.obj({}));const bytes=await doc.save(),model=await inspectPdf(bytes)
 assert.equal(model.capabilities.editMetadata,false)
 await assert.rejects(patchPdfWithReceipt(bytes,[{kind:'setMetadata',sourceSha256:model.sourceSha256,modifiedMs,metadata:values}],model.sourceSha256),/属性|保护|签名/)
})
