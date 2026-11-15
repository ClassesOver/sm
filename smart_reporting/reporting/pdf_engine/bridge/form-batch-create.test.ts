import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {bodySnapshot,fieldSnapshot,createDesignField} from './form-design-create'
async function fixture(){const d=await PDFDocument.create();d.addPage([400,500]).drawText('Keep first',{x:30,y:450});d.addPage([400,500]).drawText('Keep second',{x:30,y:450});return d.save()}
async function ops(bytes:Uint8Array){const m=await inspectPdf(bytes);return [
 {kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,fieldName:'customer.name',fieldKind:'text',rect:[30,300,180,325],required:true,value:'Alice',fontSize:12},
 {kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[1]!.pageId,fieldName:'customer.agree',fieldKind:'checkbox',rect:[30,300,50,320],required:false,checked:true},
 {kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,fieldName:'customer.date',fieldKind:'date',rect:[30,240,180,265],required:false,value:'2026-11-14',dateFormat:'yyyy-mm-dd'},
 ]}
test('multiple form fields share one immutable source and preserve pages hierarchy values and original indices',async()=>{
 const bytes=await fixture(),operations=await ops(bytes),copy=JSON.stringify(operations),before=await PDFDocument.load(bytes),result=await patchPdfWithReceipt(bytes,operations,sha256(bytes)),out=await PDFDocument.load(result.bytes),form=out.getForm()
 assert.deepEqual(result.appliedOperationIndices,[0,1,2]);assert.deepEqual(result.skippedOperations,[]);assert.equal(JSON.stringify(operations),copy);assert.equal(result.sourceSha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes))
 assert.equal(form.getTextField('customer.name').getText(),'Alice');assert.equal(form.getCheckBox('customer.agree').isChecked(),true);assert.equal(form.getTextField('customer.date').getText(),'2026-11-14');assert.deepEqual(bodySnapshot(out),bodySnapshot(before))
 assert.equal((await patchPdfWithReceipt(bytes,operations,sha256(bytes))).previewDigest,result.previewDigest)
 assert.notEqual((await patchPdfWithReceipt(bytes,[...operations].reverse(),sha256(bytes))).previewDigest,result.previewDigest)
})
test('all original identities configs page bounds and new-name conflicts reject before any field writer',async(t)=>{
 const bytes=await fixture(),operations=await ops(bytes),save=PDFDocument.prototype.save;let writes=0
 t.mock.method(PDFDocument.prototype,'save',async function(...args:Parameters<typeof save>){writes++;return save.apply(this,args)})
 for(const patch of [{sourceSha256:'0'.repeat(64)},{pageId:'forged'},{fieldName:'customer.name'},{fieldName:'customer'},{rect:[-1,300,40,330]},{checked:'yes'}])await assert.rejects(patchPdfWithReceipt(bytes,[operations[0],{...operations[1],...patch}],sha256(bytes)))
 assert.equal(writes,0)
})
test('later writer failures retain earlier created fields with honest original-index skips',async(t)=>{
 const bytes=await fixture(),operations=await ops(bytes),expected=await createDesignField(bytes,sha256(bytes),operations[0] as Parameters<typeof createDesignField>[2]),save=PDFDocument.prototype.save;let writes=0
 t.mock.method(PDFDocument.prototype,'save',async function(this:PDFDocument,...args:Parameters<typeof save>){if(++writes>=2)throw Error('injected later form write failure');return save.apply(this,args)})
 const result=await patchPdfWithReceipt(bytes,operations,sha256(bytes));assert.deepEqual(result.bytes,expected.bytes);assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations.map(skip=>skip.operationIndex),[1,2]);assert.ok(result.skippedOperations.every(skip=>skip.reason.includes('injected later form write failure')))
})
test('radio widgets retain their original cross-page mapping within a mixed creation batch',async()=>{
 const bytes=await fixture(),base=await ops(bytes),radio={kind:'createFormField',sourceSha256:sha256(bytes),pageId:base[0]!.pageId,fieldName:'answer',fieldKind:'radio',rect:[30,160,50,180],required:true,radioWidgets:[{pageId:base[0]!.pageId,rect:[30,160,50,180],exportValue:'Yes'},{pageId:base[1]!.pageId,rect:[30,160,50,180],exportValue:'No',checked:true}]}
 const result=await patchPdfWithReceipt(bytes,[base[0],radio,base[1]],sha256(bytes)),out=await PDFDocument.load(result.bytes),group=out.getForm().getRadioGroup('answer')
 assert.deepEqual(result.appliedOperationIndices,[0,1,2]);assert.deepEqual(result.skippedOperations,[]);assert.equal(group.getSelected(),'No');assert.deepEqual(group.getOptions(),['Yes','No'])
 const inspected=await inspectPdf(result.bytes);assert.deepEqual(inspected.formDesignWidgets.filter(widget=>widget.fieldName==='answer').map(widget=>widget.pageIndex),[0,1])
 await assert.rejects(patchPdfWithReceipt(bytes,[base[0],{...radio,radioWidgets:[radio.radioWidgets[0],{...radio.radioWidgets[1],pageId:'forged'}]}],sha256(bytes)))
})
