import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFNumber,PDFSignature,degrees} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {bodySnapshot,fieldSnapshot} from './form-design-create'
async function fixture(){const d=await PDFDocument.create();d.addPage([400,500]).drawText('Original empty signature',{x:30,y:450});const p=d.addPage([400,500]);p.setCropBox(20,30,360,450);p.setRotation(degrees(90));const bytes=await d.save(),m=await inspectPdf(bytes),result=await patchPdfWithReceipt(bytes,[{kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,fieldName:'SignHere',fieldKind:'signature',rect:[30,200,190,244],required:true}],sha256(bytes));assert.deepEqual(result.skippedOperations,[]);return result.bytes}
async function operation(bytes:Uint8Array){const m=await inspectPdf(bytes),w=m.formDesignWidgets[0]!;return {kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[1]!.pageId,fieldName:'SignHere_copy1',fieldKind:'signature',rect:[60,220,220,264],required:true,copyFrom:{fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256}}}
test('copies empty signature as one merged root/widget reference with no signature data across rotated crop pages',async()=>{
 const bytes=await fixture(),m=await inspectPdf(bytes);assert.equal(m.formDesignWidgets[0]!.copyEditable,true)
 const before=await PDFDocument.load(bytes),result=await patchPdfWithReceipt(bytes,[await operation(bytes)],sha256(bytes)),out=await PDFDocument.load(result.bytes),f=out.getForm().getField('SignHere_copy1'),source=out.getForm().getField('SignHere')
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[]);assert.ok(f instanceof PDFSignature);assert.equal(f.isRequired(),true);assert.deepEqual(bodySnapshot(out),bodySnapshot(before));assert.deepEqual(fieldSnapshot(out,'SignHere_copy1'),fieldSnapshot(before))
 assert.strictEqual(f.acroField.getWidgets()[0]!.dict,f.acroField.dict);assert.notEqual(String(f.ref),String(source.ref));assert.equal(out.getForm().acroForm.dict.lookup(PDFName.of('Fields'),PDFArray).asArray().filter(ref=>String(ref)===String(f.ref)).length,1);assert.equal(out.getPage(1).node.lookup(PDFName.of('Annots'),PDFArray).asArray().filter(ref=>String(ref)===String(f.ref)).length,1);assert.equal(String(f.acroField.dict.get(PDFName.of('P'))),String(out.getPage(1).ref))
 for(const key of ['V','DV','AP','ByteRange','Contents','Kids','Parent','Lock','SV'])assert.equal(f.acroField.dict.has(PDFName.of(key)),false,key)
 const color=(field:typeof f)=>field.acroField.dict.lookup(PDFName.of('MK'),PDFDict).lookup(PDFName.of('BC'),PDFArray),oldColor=color(source).toString();assert.equal(color(f).toString(),oldColor);assert.notStrictEqual(color(f),color(source));color(f).set(0,PDFNumber.of(1));const changed=await PDFDocument.load(await out.save({updateFieldAppearances:false}));assert.equal(color(changed.getForm().getField('SignHere')).toString(),oldColor)
 const model=await inspectPdf(result.bytes);assert.deepEqual(model.digitalSignatures,[]);assert.equal(model.formDesignWidgets.find(w=>w.fieldName==='SignHere_copy1')!.copyEditable,true);assert.equal(model.formDesignWidgets.find(w=>w.fieldName==='SignHere_copy1')!.pageIndex,1)
})
test('empty signature templates preflight before any save and reject supplied values appearances or fake identities',async(t)=>{
 const bytes=await fixture(),op=await operation(bytes),save=PDFDocument.prototype.save;let writes=0;t.mock.method(PDFDocument.prototype,'save',async function(...args:Parameters<typeof save>){writes++;return save.apply(this,args)})
 for(const patch of [{value:'signed'},{required:false},{fieldName:'parent.copy'},{rect:[60,220,230,264]},{copyFrom:{...op.copyFrom,widgetIdentity:'0'.repeat(64)}}])await assert.rejects(patchPdfWithReceipt(bytes,[op,{...op,fieldName:'SignHere_copy2',...patch}],sha256(bytes)))
 assert.equal(writes,0)
})
test('signed or extended source signature dictionaries never become copyable empty placeholders',async()=>{
 for(const key of ['V','DV','AP','Lock','SV','AA','ByteRange','Unexpected']){
  const bytes=await fixture(),d=await PDFDocument.load(bytes),f=d.getForm().getField('SignHere');f.acroField.dict.set(PDFName.of(key),d.context.obj(key==='V'?{Type:'Sig'}:{}));const changed=await d.save({updateFieldAppearances:false}),m=await inspectPdf(changed);assert.equal(m.formDesignWidgets[0]?.copyEditable,false,key)
  await assert.rejects(patchPdfWithReceipt(changed,[await operation(changed)],sha256(changed)))
 }
})
test('multiple empty signature copies retain original operation indices and postwrite warnings retain actual placeholders',async(t)=>{
 const bytes=await fixture(),op=await operation(bytes),result=await patchPdfWithReceipt(bytes,[op,{...op,fieldName:'SignHere_copy2'}],sha256(bytes));assert.deepEqual(result.appliedOperationIndices,[0,1]);assert.deepEqual(result.skippedOperations,[]);assert.equal((await PDFDocument.load(result.bytes)).getForm().getFields().length,3)
 const load=PDFDocument.load;t.mock.method(PDFDocument,'load',async function(input:Parameters<typeof load>[0],options:Parameters<typeof load>[1]){if(input instanceof Uint8Array&&sha256(input)!==sha256(bytes))throw Error('injected empty signature review');return load.call(PDFDocument,input,options)})
 const warning=await patchPdfWithReceipt(bytes,[op],sha256(bytes));t.mock.restoreAll();assert.match(warning.skippedOperations[0]!.reason,/output_review_failed.*injected empty signature review/);assert.ok((await PDFDocument.load(warning.bytes)).getForm().getField('SignHere_copy1') instanceof PDFSignature)
})
