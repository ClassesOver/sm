import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFNumber,PDFRawStream,decodePDFRawStream} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {inspectTextObjects,loadPdfium} from '../src/main/text-edit'

async function fixture(){const d=await PDFDocument.create();d.addPage([500,500]).drawText('Original target',{x:60,y:350,size:14});d.addPage([500,500]).drawText('Other page',{x:60,y:350,size:14});return d.save()}
async function operations(bytes:Uint8Array):Promise<Record<string,unknown>[]>{const model=await inspectPdf(bytes,true),sourceSha256=model.sourceSha256,pageId=model.pages[0]!.pageId,target=model.pages[0]!.textObjects!.find(t=>t.text==='Original target')!;return [
 {kind:'addDrawing',pageId,shape:'rect',rect:[50,330,150,370],color:[1,0,0],width:2},
 {kind:'replaceText',sourceSha256,pageId,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'New text\nSecond line',font:'courier',fontSize:12,lineLeading:20},
 {kind:'addMarkup',pageId,markupType:'underline',quads:[[50,360,150,360,50,340,150,340]],color:[0,0,1]},
 {kind:'addDrawing',sourceSha256,pageId,shape:'ellipse',rect:[200,200,260,240],color:[0,1,0],width:3},
 ]}
test('styled text and safe vector drawings keep original indices and source-bound markup mappings',async()=>{
 const source=await fixture(),ops=await operations(source),result=await patchPdfWithReceipt(source,ops,sha256(source));assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0,1,2,3]);assert.equal(result.sha256,sha256(result.bytes));assert.equal(result.sourceSha256,sha256(source))
 const out=await PDFDocument.load(result.bytes),annots=out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(annots.size(),3);assert.deepEqual(Array.from({length:annots.size()},(_,i)=>String(annots.lookup(i,PDFDict).get(PDFName.of('Subtype')))),['Underline','Square','Circle'].map(value=>'/'+value))
 for(const [slot,rect,color,width]of [[1,[46,326,154,374],[1,0,0],2],[2,[195,195,265,245],[0,1,0],3]]as const){const a=annots.lookup(slot,PDFDict),ap=a.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'));assert.ok(ap instanceof PDFRawStream);assert.equal(String(a.get(PDFName.of('Rect'))),out.context.obj(rect).toString());assert.equal(String(a.get(PDFName.of('C'))),out.context.obj(color).toString());assert.equal(a.lookup(PDFName.of('BS'),PDFDict).lookup(PDFName.of('W'),PDFNumber).asNumber(),width);assert.ok(decodePDFRawStream(ap).decode().length>10)}
 assert.ok('pendingMarkupMapping'in result);assert.deepEqual(result.pendingMarkupMapping?.map(m=>m.operationIndex),[2]);assert.ok(result.pendingMarkupMapping?.every(m=>m.pageId===ops[2]!.pageId&&m.effectivePageId===`sha256:${result.sha256}:page:0`))
 const texts=await inspectTextObjects(result.bytes);assert.ok(texts[0]!.some(t=>t.text==='New text'&&/LiberationMono/.test(t.fontName)));assert.ok(texts[0]!.some(t=>t.text==='Second line'));assert.equal(texts[1]![0]!.text,'Other page');assert.equal((await patchPdfWithReceipt(source,ops,sha256(source))).previewDigest,result.previewDigest)
})
test('mixed vectors validate every source identity geometry and allowed shape before native writing',async()=>{
 const source=await fixture(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy;let writes=0
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{writes++;return save(...args)}
  for(const patch of [{pageId:`sha256:${'b'.repeat(64)}:page:0`},{sourceSha256:'b'.repeat(64)},{rect:[50,330,550,370]},{rect:[50,330,50,370]},{width:0},{color:[2,0,0]},{shape:'arrow',from:[20,20],to:[30,30]},{shape:'image',image:'iVBORw0KGgo='},{url:'https://example.com'},{from:[10,10]},{label:'extra'}])await assert.rejects(patchPdfWithReceipt(source,[{...ops[0],...patch},...ops.slice(1)],sha256(source)))
  const d=await PDFDocument.load(source);d.getPage(1).node.set(PDFName.of('UserUnit'),PDFNumber.of(2));const changed=await d.save(),other=await operations(changed);other[0]={...other[0],pageId:`sha256:${sha256(changed)}:page:1`};await assert.rejects(patchPdfWithReceipt(changed,other,sha256(changed)),/页面单位/);assert.equal(writes,0)
 }finally{m._PDFiumExt_SaveAsCopy=save}
})
test('styled text with vectors alone does not require a pending markup mapping',async()=>{
 const source=await fixture(),ops=(await operations(source)).filter(op=>op.kind!=='addMarkup'),result=await patchPdfWithReceipt(source,ops,sha256(source));assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0,1,2]);assert.ok('pendingMarkupMapping'in result);assert.deepEqual(result.pendingMarkupMapping,[])
 const out=await PDFDocument.load(result.bytes),annots=out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.deepEqual(Array.from({length:annots.size()},(_,i)=>String(annots.lookup(i,PDFDict).get(PDFName.of('Subtype')))),['/Square','/Circle']);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(t=>t.text==='New text'))
})
test('mixed vector writer failure retains actual styled bytes and warns at original vector and markup indices',async()=>{
 const source=await fixture(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy,load=PDFDocument.load;let written=false
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{const result=save(...args);written=!!result;return result};PDFDocument.load=async(...args)=>{if(written)throw Error('injected vector writer failure');return load.call(PDFDocument,...args)}
  const result=await patchPdfWithReceipt(source,ops,sha256(source));assert.equal(result.sha256,sha256(result.bytes));assert.notEqual(result.sha256,sha256(source));assert.deepEqual(result.appliedOperationIndices,[1]);assert.deepEqual(result.skippedOperations.map(s=>s.operationIndex),[0,2,3]);assert.match(result.skippedOperations.find(s=>s.operationIndex===0)!.reason,/pdf_text_drawing_writer_failed_generated_bytes_retained/);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(t=>t.text==='New text'))
 }finally{m._PDFiumExt_SaveAsCopy=save;PDFDocument.load=load}
})
test('mixed vector review failure retains actual vector APs and styled output with honest decisions',async()=>{
 const source=await fixture(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy,load=PDFDocument.load;let written=false,reads=0
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{const result=save(...args);written=!!result;return result};PDFDocument.load=async(...args)=>{if(written&&++reads===2)throw Error('injected vector review failure');return load.call(PDFDocument,...args)}
  const result=await patchPdfWithReceipt(source,ops,sha256(source));assert.equal(result.sha256,sha256(result.bytes));assert.deepEqual(result.appliedOperationIndices,[1]);assert.deepEqual(result.skippedOperations.map(s=>s.operationIndex),[0,2,3]);assert.match(result.skippedOperations.find(s=>s.operationIndex===3)!.reason,/pdf_text_drawing_output_review_failed_generated_bytes_retained/);PDFDocument.load=load;const out=await PDFDocument.load(result.bytes);assert.equal(out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).size(),3);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(t=>t.text==='New text'))
 }finally{m._PDFiumExt_SaveAsCopy=save;PDFDocument.load=load}
})
