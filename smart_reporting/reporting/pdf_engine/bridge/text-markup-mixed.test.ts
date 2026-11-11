import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFNumber,PDFRawStream,decodePDFRawStream} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {inspectTextObjects,loadPdfium} from '../src/main/text-edit'

async function fixture(){const d=await PDFDocument.create(),p=d.addPage([500,500]);p.drawText('First target',{x:60,y:350,size:14});p.drawText('Second target',{x:60,y:250,size:14});p.drawText('Unchanged neighbor',{x:60,y:450,size:14});d.addPage([500,500]).drawText('Other page',{x:60,y:350,size:14});return d.save()}
async function operations(bytes:Uint8Array):Promise<Record<string,unknown>[]>{const model=await inspectPdf(bytes,true),sourceSha256=model.sourceSha256,pageId=model.pages[0]!.pageId;const text=(old:string,newText:string)=>{const target=model.pages[0]!.textObjects!.find(t=>t.text===old)!;return {kind:'replaceText',sourceSha256,pageId,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText,font:'courier',fontSize:12}};return [
 {kind:'addMarkup',pageId,markupType:'underline',quads:[[60,456,190,456,60,440,190,440]],color:[1,0,0]},
 text('First target','AABBCC'),
 {kind:'highlight',sourceSha256,pageId,rect:[60,340,110,365],color:[0,1,0]},
 {...text('Second target','New second\nNext line'),font:'times',lineLeading:20},
 ]}
test('styled text plus new markups preserve source identity and original interleaved receipt indices',async()=>{
 const source=await fixture(),ops=await operations(source),before=sha256(source),result=await patchPdfWithReceipt(source,ops,before)
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0,1,2,3]);assert.equal(result.sourceSha256,before);assert.equal(result.sha256,sha256(result.bytes));assert.equal(sha256(source),before)
 const texts=await inspectTextObjects(result.bytes);assert.ok(texts[0]!.some(t=>t.text==='AABBCC'&&/LiberationMono/.test(t.fontName)));assert.ok(texts[0]!.some(t=>t.text==='New second'));assert.ok(texts[0]!.some(t=>t.text==='Next line'));assert.ok(texts[0]!.some(t=>t.text==='Unchanged neighbor'));assert.equal(texts[1]![0]!.text,'Other page');assert.ok(!texts[0]!.some(t=>/First target|Second target/.test(t.text)))
 const out=await PDFDocument.load(result.bytes),annots=out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(annots.size(),2);assert.equal(String(annots.lookup(0,PDFDict).get(PDFName.of('Subtype'))),'/Underline');assert.equal(String(annots.lookup(1,PDFDict).get(PDFName.of('Subtype'))),'/Highlight')
 assert.ok('pendingMarkupMapping'in result);assert.deepEqual(result.pendingMarkupMapping?.map(m=>m.operationIndex),[0,2]);assert.ok(result.pendingMarkupMapping?.every(m=>m.pageId===ops[0]!.pageId&&m.effectivePageId===`sha256:${result.sha256}:page:0`))
 assert.equal((await patchPdfWithReceipt(source,ops,before)).previewDigest,result.previewDigest)
})
test('mixed source identity and all markup geometry are checked before any text writer',async()=>{
 const source=await fixture(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy;let writes=0
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{writes++;return save(...args)}
  for(const patch of [{pageId:'sha256:'+'b'.repeat(64)+':page:0'},{sourceSha256:'b'.repeat(64)},{quads:[[60,456,190,456,60,-10,190,-10]]}])await assert.rejects(patchPdfWithReceipt(source,[{...ops[0],...patch},...ops.slice(1)],sha256(source)))
  await assert.rejects(patchPdfWithReceipt(source,[ops[0],{...ops[1],sourceSha256:'b'.repeat(64)},...ops.slice(2)],sha256(source)))
  await assert.rejects(patchPdfWithReceipt(source,[...ops,{kind:'rotatePage',pageId:ops[0]!.pageId,delta:90}],sha256(source)),/分别保存/)
  assert.equal(writes,0)
 }finally{m._PDFiumExt_SaveAsCopy=save}
})
test('failed styled identity retains valid markup decisions at original indices',async()=>{
 const source=await fixture(),ops=await operations(source);ops[1]={...ops[1],objectId:'stale-object'};const result=await patchPdfWithReceipt(source,ops,sha256(source))
 assert.deepEqual(result.appliedOperationIndices,[0,2,3]);assert.equal(result.skippedOperations[0]!.operationIndex,1);assert.match(result.skippedOperations[0]!.reason,/identity_invalid/);assert.equal(result.sha256,sha256(result.bytes));assert.ok((await inspectTextObjects(result.bytes))[0]!.some(t=>t.text==='First target'));assert.ok('pendingMarkupMapping'in result);assert.deepEqual(result.pendingMarkupMapping?.map(m=>m.operationIndex),[0,2])
})
test('runtime markup writer failure retains actual styled bytes and warns only original markup indices',async()=>{
 const source=await fixture(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy,load=PDFDocument.load;let written=false
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{const result=save(...args);written=!!result;return result};PDFDocument.load=async(...args)=>{if(written)throw Error('injected markup writer failure');return load.call(PDFDocument,...args)}
  const result=await patchPdfWithReceipt(source,ops,sha256(source));assert.notEqual(result.sha256,sha256(source));assert.equal(result.sha256,sha256(result.bytes));assert.deepEqual(result.appliedOperationIndices,[1,3]);assert.deepEqual(result.skippedOperations.map(s=>s.operationIndex),[0,2]);assert.ok(result.skippedOperations.every(s=>s.reason.includes('pdf_text_markup_writer_failed_generated_bytes_retained')));assert.ok((await inspectTextObjects(result.bytes))[0]!.some(t=>t.text==='AABBCC'))
 }finally{m._PDFiumExt_SaveAsCopy=save;PDFDocument.load=load}
})
test('protected source is rejected before either mixed writer',async()=>{
 const d=await PDFDocument.load(await fixture());d.catalog.set(PDFName.of('Perms'),d.context.obj({}));const source=await d.save(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy;let writes=0
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{writes++;return save(...args)};await assert.rejects(patchPdfWithReceipt(source,ops,sha256(source)),/保护、签名或表单/);assert.equal(writes,0)}finally{m._PDFiumExt_SaveAsCopy=save}
})
test('markup output review failure retains both actual text and markups with honest warnings',async()=>{
 const source=await fixture(),ops=await operations(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy,load=PDFDocument.load;let written=false,afterWriteLoads=0
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{const result=save(...args);written=!!result;return result};PDFDocument.load=async(...args)=>{if(written&&++afterWriteLoads===2)throw Error('injected output review failure');return load.call(PDFDocument,...args)}
  const result=await patchPdfWithReceipt(source,ops,sha256(source));assert.equal(result.sha256,sha256(result.bytes));assert.deepEqual(result.appliedOperationIndices,[1,3]);assert.deepEqual(result.skippedOperations.map(s=>s.operationIndex),[0,2]);assert.ok(result.skippedOperations.every(s=>s.reason.includes('pdf_text_markup_output_review_failed_generated_bytes_retained')));assert.ok('pendingMarkupMapping'in result);assert.deepEqual(result.pendingMarkupMapping,[])
  PDFDocument.load=load;const out=await PDFDocument.load(result.bytes);assert.equal(out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).size(),2);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(t=>t.text==='AABBCC'))
 }finally{m._PDFiumExt_SaveAsCopy=save;PDFDocument.load=load}
})
test('nondefault UserUnit on a styled target page rejects before either mixed writer',async()=>{
 const d=await PDFDocument.load(await fixture());d.getPage(1).node.set(PDFName.of('UserUnit'),PDFNumber.of(2));const source=await d.save(),model=await inspectPdf(source,true),target=model.pages[1]!.textObjects!.find(t=>t.text==='Other page')!,pageId=model.pages[1]!.pageId,sourceSha256=sha256(source),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy;let writes=0
 const ops=[{kind:'highlight',pageId:model.pages[0]!.pageId,rect:[60,340,110,365]}, {kind:'replaceText',pageId,sourceSha256,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'Styled other page',font:'courier',fontSize:12}]
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{writes++;return save(...args)};await assert.rejects(patchPdfWithReceipt(source,ops,sourceSha256),/页面单位/);assert.equal(writes,0)}finally{m._PDFiumExt_SaveAsCopy=save}
})
test('mixed save preserves readable existing markup appearance and maps only new annotation slots',async()=>{
 const raw=await fixture(),pageId=`sha256:${sha256(raw)}:page:0`,old={kind:'addMarkup',pageId,markupType:'squiggly',quads:[[300,456,420,456,300,440,420,440]],color:[.2,.3,.4]},source=(await patchPdfWithReceipt(raw,[old],sha256(raw))).bytes
 const snapshot=async(bytes:Uint8Array)=>{const d=await PDFDocument.load(bytes),a=d.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).lookup(0,PDFDict),ap=a.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'),PDFRawStream);return {subtype:String(a.get(PDFName.of('Subtype'))),quads:String(a.get(PDFName.of('QuadPoints'))),color:a.lookup(PDFName.of('C'),PDFArray).asArray().map(value=>Number(String(value))),appearance:sha256(decodePDFRawStream(ap).decode())}}
 const before=await snapshot(source),ops=await operations(source),result=await patchPdfWithReceipt(source,ops,sha256(source));assert.deepEqual(result.skippedOperations,[]);const after=await snapshot(result.bytes);assert.deepEqual({...after,color:undefined},{...before,color:undefined});assert.equal(after.color.length,before.color.length);assert.ok(after.color.every((value,index)=>Math.abs(value-before.color[index]!)<1e-6))
 const d=await PDFDocument.load(result.bytes),annots=d.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(annots.size(),3);assert.ok('pendingMarkupMapping'in result);assert.deepEqual(result.pendingMarkupMapping?.map(m=>m.operationIndex),[0,2]);assert.ok(result.pendingMarkupMapping?.every(m=>m.sourceRef!==String(annots.get(0))))
})
