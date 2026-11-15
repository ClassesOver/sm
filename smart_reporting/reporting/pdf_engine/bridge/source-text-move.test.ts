import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,degrees} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {inspectTextObjects,loadPdfium} from '../src/main/text-edit'
async function fixture(rotation=0){const d=await PDFDocument.create(),p=d.addPage([500,500]);p.setCropBox(10,20,480,460);p.setRotation(degrees(rotation));p.drawText('Move original',{x:60,y:350,size:14});p.drawText('Keep neighbor',{x:60,y:450,size:12});d.addPage([500,500]).drawText('Other page',{x:60,y:350,size:12});return d.save()}
async function op(bytes:Uint8Array){const m=await inspectPdf(bytes,true),t=m.pages[0]!.textObjects!.find(item=>item.text==='Move original')!;return {kind:'moveText',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,objectId:t.objectId,expectedTextSha256:t.expectedTextSha256,delta:[35,-25]}}
test('moving an original object preserves glyphs font and neighbors in every page rotation',async()=>{
 for(const rotation of [0,90,180,270]){const bytes=await fixture(rotation),operation=await op(bytes),before=await inspectTextObjects(bytes),result=await patchPdfWithReceipt(bytes,[operation],sha256(bytes)),after=await inspectTextObjects(result.bytes)
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[]);assert.equal(result.sourceSha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes))
 const original=before[0]!.find(item=>item.text==='Move original')!,moved=after[0]!.find(item=>item.text==='Move original')!
 assert.equal(moved.fontName,original.fontName);assert.equal(moved.fontSha256,original.fontSha256);assert.equal(moved.fontSize,original.fontSize)
 moved.rect.forEach((value,index)=>assert.ok(Math.abs(value-original.rect[index]!-(index%2===0?35:-25))<.05))
 assert.deepEqual(after[0]!.filter(item=>item.text!=='Move original'),before[0]!.filter(item=>item.text!=='Move original'));assert.deepEqual(after[1],before[1]);assert.equal((await PDFDocument.load(result.bytes)).getPage(0).getRotation().angle,rotation)
 assert.equal((await patchPdfWithReceipt(bytes,[operation],sha256(bytes))).previewDigest,result.previewDigest)
 }
})
test('all moved source identities duplicate targets and bounds are checked before any write',async()=>{
 const bytes=await fixture(),operation=await op(bytes),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy;let writes=0
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{writes++;return save(...args)}
 for(const patch of [{sourceSha256:'0'.repeat(64)},{pageId:'forged'},{objectId:'stale'},{expectedTextSha256:'0'.repeat(64)},{delta:[1000,0]},{delta:[NaN,0]}])await assert.rejects(patchPdfWithReceipt(bytes,[{...operation,...patch}],sha256(bytes)))
 await assert.rejects(patchPdfWithReceipt(bytes,[operation,operation],sha256(bytes)))
 await assert.rejects(patchPdfWithReceipt(bytes,[operation,{kind:'rotatePage',pageId:operation.pageId,delta:90}],sha256(bytes)))
 assert.equal(writes,0)
 }finally{m._PDFiumExt_SaveAsCopy=save}
})
test('post-write movement review failure retains actual translated bytes with honest warnings',async()=>{
 const bytes=await fixture(),operation=await op(bytes),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy,type=m._FPDFPageObj_GetType;let written=false,result:Awaited<ReturnType<typeof patchPdfWithReceipt>>
 try{m._PDFiumExt_SaveAsCopy=(...args)=>{const value=save(...args);written=!!value;return value};m._FPDFPageObj_GetType=(...args)=>{if(written)throw Error('injected movement review failure');return type(...args)}
 result=await patchPdfWithReceipt(bytes,[operation],sha256(bytes));assert.notEqual(result.sha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes));assert.deepEqual(result.appliedOperationIndices,[]);assert.deepEqual(result.skippedOperations.map(skip=>skip.operationIndex),[0]);assert.match(result.skippedOperations[0]!.reason,/review_failed/)
 }finally{m._PDFiumExt_SaveAsCopy=save;m._FPDFPageObj_GetType=type}
 const after=(await inspectTextObjects(result!.bytes))[0]!.find(item=>item.text==='Move original')!;assert.ok(after.rect[0]>90)
})
test('movement preserves the linear transform of rotated original text',async()=>{
 const d=await PDFDocument.create(),p=d.addPage([500,500]);p.drawText('Move original',{x:60,y:300,size:14,rotate:degrees(25)})
 const bytes=await d.save(),operation=await op(bytes),before=(await inspectTextObjects(bytes))[0]![0]!,result=await patchPdfWithReceipt(bytes,[operation],sha256(bytes)),after=(await inspectTextObjects(result.bytes))[0]![0]!
 assert.deepEqual(result.skippedOperations,[]);assert.equal(after.fontName,before.fontName);after.rect.forEach((value,index)=>assert.ok(Math.abs(value-before.rect[index]!-(index%2===0?35:-25))<.05))
})
test('multiple independent source objects across pages retain their original indices and fonts',async()=>{
 const bytes=await fixture(),first=await op(bytes),model=await inspectPdf(bytes,true),target=model.pages[1]!.textObjects![0]!,second={kind:'moveText',sourceSha256:model.sourceSha256,pageId:model.pages[1]!.pageId,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,delta:[10,-10]},before=await inspectTextObjects(bytes)
 const result=await patchPdfWithReceipt(bytes,[first,second],sha256(bytes)),after=await inspectTextObjects(result.bytes)
 assert.deepEqual(result.appliedOperationIndices,[0,1]);assert.deepEqual(result.skippedOperations,[])
 for(const [pageIndex,text,delta]of [[0,'Move original',[35,-25]],[1,'Other page',[10,-10]]] as const){const old=before[pageIndex]!.find(item=>item.text===text)!,moved=after[pageIndex]!.find(item=>item.text===text)!;assert.equal(moved.fontName,old.fontName);assert.equal(moved.fontSha256,old.fontSha256);moved.rect.forEach((value,axis)=>assert.ok(Math.abs(value-old.rect[axis]!-delta[axis%2]!)<.05))}
 assert.deepEqual(after[0]!.filter(item=>item.text==='Keep neighbor'),before[0]!.filter(item=>item.text==='Keep neighbor'))
})
