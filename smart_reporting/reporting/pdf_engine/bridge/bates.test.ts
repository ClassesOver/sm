import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,PDFString} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt} from './operations'
import {inspectTextObjects} from '../src/main/text-edit'
import {reviewBatesOutput} from './bates'
const config={prefix:'ACME-',start:41,digits:6,fontSize:10,color:[.1,.1,.12],position:'bottom-right',firstPage:1,lastPage:null}
async function source(){const doc=await PDFDocument.create();for(let i=0;i<3;i++){const p=doc.addPage([300+i*50,400]);p.drawText('Original '+(i+1),{x:20,y:250})}doc.setTitle('Bates preserved source');return doc.save()}
const entry=(pageId:string,ordinal:number)=>({pageId,ordinal,origin:[272,28],rotate:0,lineXOffsets:[-65]})
test('Bates writes searchable prefixed sequential text to selected immutable pages and preserves source text',async()=>{
 const bytes=await source(),model=await inspectPdf(bytes)
 const operation={kind:'addBates',sourceSha256:model.sourceSha256,config:{...config,firstPage:2,lastPage:3},entries:[entry(model.pages[1].pageId,0),entry(model.pages[2].pageId,1)]}
 const result=await patchPdfWithReceipt(bytes,[operation],model.sourceSha256)
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
 const text=await inspectTextObjects(result.bytes)
 assert.deepEqual(text.map(p=>p.map(t=>t.text)),[['Original 1'],['Original 2','ACME-000041'],['Original 3','ACME-000042']])
 assert.equal((await PDFDocument.load(result.bytes)).getTitle(),'Bates preserved source')
 assert.deepEqual(result.reviewIssues,[])
})
test('Bates content keeps applied numbers through blank insertion, deletion, later reorder and rotation',async()=>{
 const bytes=await source(),model=await inspectPdf(bytes),[a,b,c]=model.pages.map(p=>p.pageId)
 const operation={kind:'addBates',sourceSha256:model.sourceSha256,config,entries:[entry(c,0),entry('blank:bates',1),entry(a,2)]}
 const result=await patchPdfWithReceipt(bytes,[{kind:'insertBlankPage',pageId:'blank:bates',width:300,height:400},operation,{kind:'deletePage',pageId:a},{kind:'rotatePage',pageId:c,delta:90},{kind:'reorderPages',pageIds:['blank:bates',b,c]}],model.sourceSha256)
 assert.deepEqual(result.skippedOperations,[])
 const text=await inspectTextObjects(result.bytes)
 assert.deepEqual(text.map(p=>p.map(t=>t.text)),[['ACME-000042'],['Original 2'],['Original 3','ACME-000041']])
 const doc=await PDFDocument.load(result.bytes);assert.equal(doc.getPage(2).getRotation().angle,90)
})
test('Bates validates source, target identities, sequence, range and style before writing',async()=>{
 const bytes=await source(),model=await inspectPdf(bytes),base={kind:'addBates',sourceSha256:model.sourceSha256,config,entries:[entry(model.pages[0].pageId,0)]}
 for(const op of [{...base,sourceSha256:'f'.repeat(64)},{...base,entries:[entry('foreign',0)]},{...base,entries:[entry(model.pages[0].pageId,-1)]},{...base,config:{...config,digits:16}},{...base,config:{...config,fontSize:37}},{...base,config:{...config,lastPage:0}},{...base,entries:[entry(model.pages[0].pageId,0),entry(model.pages[0].pageId,1)]}])await assert.rejects(patchPdfWithReceipt(bytes,[op],model.sourceSha256))
})
test('Bates post-write review failures are advisory and return a specific issue',async()=>{
 const issues=await reviewBatesOutput(new Uint8Array([1,2,3]),[{operationIndex:2,pageId:'p',input:{pageIndex:0,origin:[20,20],text:'CASE-001',fontSize:10,color:[0,0,0]}}],[0])
 assert.equal(issues[0].operationIndex,2);assert.equal(issues[0].code,'pdf_bates_output_review_failed');assert.equal(issues[0].kind,'addBates')
})
test('Bates retains existing notes and composes with new source-bound notes',async()=>{
 const doc=await PDFDocument.load(await source()),first=doc.getPage(0)
 first.node.set(PDFName.of('Annots'),doc.context.obj([doc.context.register(doc.context.obj({Type:'Annot',Subtype:'Text',Rect:[10,10,30,28],Contents:PDFString.of('Existing note')}))]))
 const bytes=await doc.save(),model=await inspectPdf(bytes),pageId=model.pages[0].pageId
 const result=await patchPdfWithReceipt(bytes,[{kind:'addBates',sourceSha256:model.sourceSha256,config,entries:[entry(pageId,0)]},{kind:'addTextAnnotation',pageId,rect:[50,60,80,90],text:'Added note',createdMs:0}],model.sourceSha256)
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.reviewIssues,[])
 const reread=await inspectPdf(result.bytes);assert.deepEqual(reread.pages[0].notes.map(note=>note.contents),['Existing note','Added note'])
})
test('Bates rejects protected source capability before modifying it',async()=>{
 const doc=await PDFDocument.load(await source());doc.catalog.set(PDFName.of('Perms'),doc.context.obj({}))
 const bytes=await doc.save(),model=await inspectPdf(bytes)
 assert.equal(model.capabilities.bates,false)
 await assert.rejects(patchPdfWithReceipt(bytes,[{kind:'addBates',sourceSha256:model.sourceSha256,config,entries:[entry(model.pages[0].pageId,0)]}],model.sourceSha256),/签名|保护/)
})
