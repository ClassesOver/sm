import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,PDFDict,PDFArray,PDFString} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt} from './operations'
import {applySaveRequest} from '../src/main/save-pdf'
import {reviewPdfOutline} from './outline'

async function fixture() {
 const document=await PDFDocument.create();document.addPage([300,400]);document.addPage([350,450]);document.addPage([400,500])
 document.setTitle('Preserved title')
 return (await applySaveRequest(await document.save(),{path:'',markups:[],drawings:[],formValues:[],outline:[{title:'First',pageIndex:0,top:320,children:[{title:'Child',pageIndex:1}]},{title:'Last',pageIndex:2}]})).bytes
}
const entry=(title:string,pageId:string,children:any[]=[],top:number|null=null)=>({title,pageId,top,children})
test('inspects the real nested source outline and persists rename/add/delete without changing pages',async()=>{
 const source=await fixture(),model=await inspectPdf(source)
 assert.equal(model.outlineEditable,true)
 assert.deepEqual(model.outline,[entry('First',model.pages[0].pageId,[entry('Child',model.pages[1].pageId)],320),entry('Last',model.pages[2].pageId)])
 const tree=[entry('重命名',model.pages[0].pageId,[],320),entry('新增',model.pages[1].pageId)]
 const operations=[{kind:'setOutline',sourceSha256:model.sourceSha256,tree}]
 const output=await patchPdfWithReceipt(source,operations,model.sourceSha256),again=await patchPdfWithReceipt(source,operations,model.sourceSha256)
 assert.equal(output.sha256,again.sha256);assert.equal(output.previewDigest,again.previewDigest)
 const after=await inspectPdf(output.bytes)
 assert.deepEqual(after.outline,[entry('重命名',after.pages[0].pageId,[],320),entry('新增',after.pages[1].pageId)])
 assert.equal(after.pageCount,3);assert.equal((await PDFDocument.load(output.bytes)).getTitle(),'Preserved title')
 assert.deepEqual(output.skippedOperations,[]);assert.deepEqual(output.appliedOperationIndices,[0]);assert.deepEqual(output.reviewIssues,[])
})
test('outline composes with blank insertion, page reorder, deletion, rotation and notes using immutable page targets',async()=>{
 const source=await fixture(),model=await inspectPdf(source),[first,second,last]=model.pages
 const operations=[{kind:'insertBlankPage',pageId:'blank:outline-test',width:300,height:400},{kind:'setOutline',sourceSha256:model.sourceSha256,tree:[entry('First',first.pageId,[entry('Removed child',second.pageId)]),entry('Blank','blank:outline-test'),entry('Last',last.pageId)]},{kind:'deletePage',pageId:second.pageId},{kind:'rotatePage',pageId:last.pageId,delta:90},{kind:'addTextAnnotation',pageId:first.pageId,rect:[10,10,40,40],text:'Keep note'},{kind:'reorderPages',pageIds:[last.pageId,'blank:outline-test',first.pageId]}]
 const result=await patchPdfWithReceipt(source,operations,model.sourceSha256),after=await inspectPdf(result.bytes)
 assert.deepEqual(after.outline,[entry('First',after.pages[2].pageId),entry('Blank',after.pages[1].pageId),entry('Last',after.pages[0].pageId)])
 assert.equal(after.pages[0].rotation,90);assert.equal(after.pages[2].notes[0].contents,'Keep note')
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0,1,2,3,4,5]);assert.deepEqual(result.reviewIssues,[])
})
test('explicit empty outline and removal of all targeted pages produce a readable empty tree',async()=>{
 const source=await fixture(),model=await inspectPdf(source)
 for(const operations of [[{kind:'setOutline',sourceSha256:model.sourceSha256,tree:[]}],[{kind:'setOutline',sourceSha256:model.sourceSha256,tree:[entry('Gone',model.pages[0].pageId)]},{kind:'deletePage',pageId:model.pages[0].pageId}]]){
  const after=await inspectPdf((await patchPdfWithReceipt(source,operations,model.sourceSha256)).bytes)
  assert.deepEqual(after.outline,[]);assert.equal(after.outlineEditable,true)
 }
})
test('URI actions, broken destinations and cyclic trees remain readable by existing viewer but cannot be replaced',async()=>{
 for(const kind of ['url','missing','cycle']){
  const document=await PDFDocument.load(await fixture()),root=document.catalog.lookup(PDFName.of('Outlines'),PDFDict),first=root.lookup(PDFName.of('First'),PDFDict)
  if(kind==='url'){first.delete(PDFName.of('Dest'));first.set(PDFName.of('A'),document.context.obj({S:'URI',URI:PDFString.of('https://example.com/bookmark')}))}
  if(kind==='missing')first.set(PDFName.of('Dest'),document.context.obj([999,'XYZ',0,null,null]))
  if(kind==='cycle')first.set(PDFName.of('Next'),root.get(PDFName.of('First'))!)
  const source=await document.save(),model=await inspectPdf(source)
  assert.equal(model.outlineEditable,false,kind);assert.ok(model.outlineReason)
  await assert.rejects(()=>patchPdfWithReceipt(source,[{kind:'setOutline',sourceSha256:model.sourceSha256,tree:[]}],model.sourceSha256),/书签/)
 }
})
test('named destinations resolve to the same source page before editing',async()=>{
 const document=await PDFDocument.load(await fixture()),root=document.catalog.lookup(PDFName.of('Outlines'),PDFDict),first=root.lookup(PDFName.of('First'),PDFDict)
 const target=first.lookup(PDFName.of('Dest'),PDFArray)
 document.catalog.set(PDFName.of('Names'),document.context.obj({Dests:{Names:[PDFString.of('named-first'),target]}}));first.set(PDFName.of('Dest'),PDFString.of('named-first'))
 const source=await document.save(),model=await inspectPdf(source)
 assert.equal(model.outlineEditable,true);assert.equal(model.outline[0].pageId,model.pages[0].pageId);assert.equal(model.outline[0].top,320)
})
test('stale source, foreign pages, malformed trees and duplicate replacements are rejected before writing',async()=>{
 const source=await fixture(),model=await inspectPdf(source),valid={kind:'setOutline',sourceSha256:model.sourceSha256,tree:[entry('Valid',model.pages[0].pageId)]}
 for(const operations of [[{...valid,sourceSha256:'0'.repeat(64)}],[{...valid,tree:[entry('Foreign','sha256:foreign:page:0')]}],[{...valid,tree:[entry('',model.pages[0].pageId)]}],[{...valid,tree:[{...entry('Unknown',model.pages[0].pageId),url:'https://example.com'}]}],[{...valid,tree:[entry('Infinity',model.pages[0].pageId,[],Infinity)]}],[valid,valid]])await assert.rejects(()=>patchPdfWithReceipt(source,operations,model.sourceSha256))
})
test('post-write outline review faults return an advisory issue and retain the generated bytes',async()=>{
 const source=await fixture(),model=await inspectPdf(source)
 const generated=await patchPdfWithReceipt(source,[{kind:'setOutline',sourceSha256:model.sourceSha256,tree:[]}],model.sourceSha256)
 const before=Buffer.from(generated.bytes)
 const issues=await reviewPdfOutline(generated.bytes,[{title:'Mismatch',pageIndex:0}],model.pages.map(page=>page.index),model.sourceSha256,0)
 assert.equal(issues.length,1);assert.equal(issues[0].code,'pdf_outline_output_review_failed');assert.match(issues[0].message,/已保留实际生成文件/)
 assert.deepEqual(Buffer.from(generated.bytes),before);assert.equal((await inspectPdf(generated.bytes)).pageCount,3)
})
