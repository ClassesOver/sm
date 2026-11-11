/** 待保存文字标注只按真实追加槽位签发身份，重复内容不能模糊匹配。 */
import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFArray,PDFDict,PDFDocument,PDFName} from 'pdf-lib'
import * as operations from './operations'
import {applySaveRequest} from '../src/main/save-pdf'
async function fixture(){const doc=await PDFDocument.create();doc.addPage([300,300]);doc.addPage([300,300]);return doc.save()}
const mark=(pageId:string)=>({kind:'addMarkup',pageId,markupType:'highlight',quads:[[30,100,90,100,30,80,90,80]],color:[1,.85,0]})
const legacy=(pageId:string)=>({kind:'highlight',pageId,rect:[30,80,90,100]})
const request=()=>({path:'',markups:[{pageIndex:0,type:'highlight' as const,quads:[[30,100,90,100,30,80,90,80]] as [number,number,number,number,number,number,number,number][],color:[1,.85,0] as [number,number,number]}],drawings:[],formValues:[],rotations:[],deletedPages:[]})
test('duplicate markup operations bind distinct real append slots through mixed drawings and page reorder',async()=>{
 const source=await fixture(),model=await operations.inspectPdf(source),[a,b]=model.pages
 const result=await operations.patchPdfWithReceipt(source,[mark(a.pageId),{kind:'addTextAnnotation',pageId:a.pageId,rect:[120,120,140,140],text:'note'},legacy(a.pageId),mark(b.pageId),{kind:'reorderPages',pageIds:[b.pageId,a.pageId]}],model.sourceSha256)
 assert.ok(Array.isArray(result.pendingMarkupMapping),'receipt exposes verified markup mapping')
 const output=await operations.inspectPdf(result.bytes)
 assert.deepEqual(result.pendingMarkupMapping.map(m=>m.operationIndex),[0,2,3])
 const expected=[output.pages[1].markups[0],output.pages[1].markups[1],output.pages[0].markups[0]]
 for(const [index,mapping] of result.pendingMarkupMapping.entries()){
  assert.equal(mapping.pageId,index===2?b.pageId:a.pageId)
  assert.equal(mapping.effectivePageId,output.pages[index===2?0:1].pageId)
  for(const key of ['annotationId','sourceRef','expectedAnnotationSha256'])assert.equal(mapping[key],expected[index][key])
 }
 assert.notEqual(result.pendingMarkupMapping[0].sourceRef,result.pendingMarkupMapping[1].sourceRef)
})
test('removed source annotation is excluded from append prefix and surviving page identities follow deletion',async()=>{
 const source=await fixture(),model=await operations.inspectPdf(source)
 const seeded=await operations.patchPdfWithReceipt(source,[mark(model.pages[1].pageId)],model.sourceSha256),before=await operations.inspectPdf(seeded.bytes),saved=before.pages[1].markups[0]
 const result=await operations.patchPdfWithReceipt(seeded.bytes,[{kind:'removeMarkup',pageId:before.pages[1].pageId,annotationId:saved.annotationId,expectedAnnotationSha256:saved.expectedAnnotationSha256},legacy(before.pages[1].pageId),{kind:'deletePage',pageId:before.pages[0].pageId}],before.sourceSha256)
 assert.ok(Array.isArray(result.pendingMarkupMapping),'receipt exposes verified markup mapping')
 const output=await operations.inspectPdf(result.bytes)
 assert.equal(result.pendingMarkupMapping.length,1)
 assert.equal(result.pendingMarkupMapping[0].operationIndex,1)
 assert.equal(result.pendingMarkupMapping[0].sourceRef,output.pages[0].markups[0].sourceRef)
 assert.equal(result.pendingMarkupMapping[0].effectivePageId,output.pages[0].pageId)
})
test('page size transformation conservatively withholds pending markup mapping',async()=>{
 const source=await fixture(),model=await operations.inspectPdf(source)
 const result=await operations.patchPdfWithReceipt(source,[mark(model.pages[0].pageId),{kind:'setPageSize',preset:'A4'}],model.sourceSha256)
 assert.deepEqual(result.pendingMarkupMapping,[])
})
test('append verifier rejects changed payload, reused refs, missing slots and cross-page shared refs',async()=>{
 assert.equal(typeof operations.inspectAddedMarkupReferences,'function','real append verifier is available')
 const source=await fixture(),req=request(),saved=await applySaveRequest(source,req)
 const verify=(bytes:Uint8Array)=>operations.inspectAddedMarkupReferences(source,bytes,req.markups,req.drawings,[0,1])
 assert.equal((await verify(saved.bytes)).size,1)
 for(const mutation of ['missing','payload','shared','old-ref']){
  const doc=await PDFDocument.load(saved.bytes),annots=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  if(mutation==='missing')annots.remove(0)
  if(mutation==='payload')annots.lookup(0,PDFDict).set(PDFName.of('C'),doc.context.obj([0,0,0]))
  if(mutation==='shared')doc.getPage(1).node.set(PDFName.of('Annots'),annots)
  if(mutation==='old-ref')annots.set(0,doc.getPage(0).ref)
  assert.equal((await verify(await doc.save())).size,0,mutation)
 }
})
test('existing identical source markup remains outside mapping and all markup types use distinct refs',async()=>{
 const source=await fixture(),model=await operations.inspectPdf(source),seeded=await operations.patchPdfWithReceipt(source,[mark(model.pages[0].pageId)],model.sourceSha256),before=await operations.inspectPdf(seeded.bytes)
 const ops=['highlight','underline','squiggly','strikeout'].map(markupType=>({...mark(before.pages[0].pageId),markupType}))
 const result=await operations.patchPdfWithReceipt(seeded.bytes,ops,before.sourceSha256),output=await operations.inspectPdf(result.bytes)
 assert.equal(result.pendingMarkupMapping.length,4)
 assert.equal(new Set(result.pendingMarkupMapping.map(m=>m.sourceRef)).size,4)
 assert.ok(result.pendingMarkupMapping.every(m=>m.sourceRef!==before.pages[0].markups[0].sourceRef))
 assert.deepEqual(result.pendingMarkupMapping.map(m=>m.annotationId),output.pages[0].markups.slice(1).map(m=>m.annotationId))
 const digestInput={sourceSha256:before.sourceSha256,operations:ops,appliedOperationIndices:result.appliedOperationIndices,skippedOperations:result.skippedOperations,pendingNoteMapping:result.pendingNoteMapping,pendingMarkupMapping:result.pendingMarkupMapping,outputIdentity:null,savedFormFields:[],resources:null,resizedIdentity:null,markupOutputSha256:operations.sha256(result.bytes)}
 assert.equal(result.previewDigest,operations.sha256(Buffer.from(JSON.stringify(digestInput))))
 assert.notEqual(result.previewDigest,operations.sha256(Buffer.from(JSON.stringify({...digestInput,pendingMarkupMapping:[]}))))
})
