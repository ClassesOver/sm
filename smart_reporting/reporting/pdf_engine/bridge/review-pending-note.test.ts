/** 待保存批注必须由真实追加引用归属，不能按相同正文选择父线程。 */
import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFArray,PDFDict,PDFDocument,PDFHexString,PDFName,PDFString,StandardFonts} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt} from './operations'

async function fixture(){const doc=await PDFDocument.create(),font=await doc.embedFont(StandardFonts.Helvetica);doc.addPage([300,300]).drawText('Revenue is 42.',{x:30,y:210,size:12,font});return doc.save()}
const root=(pageId:string,localId?:string)=>({kind:'addTextAnnotation',pageId,...(localId?{localId}:{}),rect:[30,220,50,238],text:'Change revenue to 72.',createdMs:0})
test('actual append maps duplicate pending roots to operation indices and AI reply targets exact local root after text edit',async()=>{
 const source=await fixture(),model=await inspectPdf(source,true),p=model.pages[0],t=p.textObjects[0],localId='b'.repeat(32)
 const base=await patchPdfWithReceipt(source,[root(p.pageId),root(p.pageId,localId)],model.sourceSha256)
 assert.ok(Array.isArray(base.pendingNoteMapping),'actual preview must expose exact pending root mapping')
 assert.equal(base.pendingNoteMapping.length,2)
 assert.deepEqual(base.pendingNoteMapping.map(n=>n.operationIndex),[0,1])
 assert.notEqual(base.pendingNoteMapping[0].sourceRef,base.pendingNoteMapping[1].sourceRef)
 const result=await patchPdfWithReceipt(source,[root(p.pageId),root(p.pageId,localId),{kind:'replaceText',pageId:p.pageId,objectId:t.objectId,expectedTextSha256:t.expectedTextSha256,newText:'Revenue is 72.'},{kind:'replyPendingNote',pageId:p.pageId,parentLocalId:localId,contents:'Changed to 72.',author:'AI Assistant',createdMs:0}],model.sourceSha256)
 assert.deepEqual(result.appliedOperationIndices,[0,1,2,3]);assert.deepEqual(result.skippedOperations,[])
 assert.equal((await inspectPdf(result.bytes,true)).pages[0].textObjects.map(o=>o.text).join(''),'Revenue is 72.')
 const doc=await PDFDocument.load(result.bytes),a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray),reply=a.lookup(2,PDFDict),author=reply.lookup(PDFName.of('T'))
 assert.equal(String(reply.get(PDFName.of('IRT'))),String(a.get(1)));assert.notEqual(String(a.get(0)),String(a.get(1)))
 assert.ok(author instanceof PDFString||author instanceof PDFHexString);assert.equal(author.decodeText(),'AI Assistant')
 const inspected=await inspectPdf(result.bytes),mapping=result.pendingNoteMapping[1]
 assert.equal(mapping.annotationId,inspected.pages[0].notes[1].annotationId)
 assert.equal(mapping.expectedAnnotationSha256,inspected.pages[0].notes[1].expectedAnnotationSha256)
 assert.equal(mapping.pageId,p.pageId);assert.equal(mapping.localId,localId)
})
test('pending AI reply keeps strict author, exact root ownership and geometry boundaries',async()=>{
 const source=await fixture(),model=await inspectPdf(source,true),p=model.pages[0],id='c'.repeat(32)
 for(const extra of [{author:'Reviewer'},{sourceRef:'99R'},{parentLocalId:'d'.repeat(32)}])await assert.rejects(patchPdfWithReceipt(source,[root(p.pageId,id),{kind:'replyPendingNote',pageId:p.pageId,parentLocalId:id,contents:'Question?',createdMs:0,...extra}],model.sourceSha256))
})
