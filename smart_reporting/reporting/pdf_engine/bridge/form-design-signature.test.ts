import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFName,PDFSignature,PDFHexString,PDFRef} from 'pdf-lib'
import {createDesignField,formDesignCreateAvailability,editDesignFieldRequired} from './form-design-create'
import {inspectDesignWidgets,removeDesignWidgetWithReceipt} from './form-design'
import {editDesignWidget,editDesignWidgetRects} from './form-design-properties'
const hash=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex')
async function fixture(){const d=await PDFDocument.create();d.addPage([300,400]).drawText('preserved body');return d.save()}
async function signature(){const b=await fixture(),sha=hash(b);return createDesignField(b,sha,{kind:'createFormField',sourceSha256:sha,pageId:`sha256:${sha}:page:0`,fieldName:'Signature1',fieldKind:'signature',rect:[30,100,190,144],required:false})}
const target=(w:Awaited<ReturnType<typeof inspectDesignWidgets>>['widgets'][number])=>({fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256})
test('empty native signature survives create geometry required rename and delete',async()=>{
 let r=await signature();assert.deepEqual(r.skippedOperations,[]);let d=await PDFDocument.load(r.bytes),f=d.getForm().getField('Signature1');assert.ok(f instanceof PDFSignature);assert.equal(f.acroField.dict.has(PDFName.of('V')),false);assert.equal(f.acroField.dict.has(PDFName.of('AP')),false)
 let w=(await inspectDesignWidgets(r.bytes)).widgets[0];assert.equal(w.fieldKind,'signature');assert.equal(w.designEditable,true);assert.equal(w.removable,true)
 r=await editDesignWidgetRects(r.bytes,hash(r.bytes),{kind:'editFormWidgetRects',sourceSha256:hash(r.bytes),changes:[{...target(w),rect:[40,110,200,154]}]});assert.deepEqual(r.skippedOperations,[])
 w=(await inspectDesignWidgets(r.bytes)).widgets[0];r=await editDesignWidget(r.bytes,hash(r.bytes),{kind:'editFormWidget',sourceSha256:hash(r.bytes),...target(w),required:true});assert.deepEqual(r.skippedOperations,[])
 w=(await inspectDesignWidgets(r.bytes)).widgets[0];assert.equal(w.required,true);r=await editDesignWidget(r.bytes,hash(r.bytes),{kind:'editFormWidget',sourceSha256:hash(r.bytes),...target(w),newFieldName:'Approved'});assert.deepEqual(r.skippedOperations,[])
 w=(await inspectDesignWidgets(r.bytes)).widgets[0];assert.equal(w.fieldName,'Approved');r=await removeDesignWidgetWithReceipt(r.bytes,hash(r.bytes),target(w));assert.deepEqual(r.skippedOperations,[]);d=await PDFDocument.load(r.bytes);assert.equal(d.getForm().getFields().length,0)
})
test('signed values lock seed actions and shared identities remain protected',async()=>{
 const original=await signature();for(const key of ['V','DV','Lock','SV','AA','ByteRange']){const d=await PDFDocument.load(original.bytes),f=d.getForm().getField('Signature1');f.acroField.dict.set(PDFName.of(key),key==='V'?PDFHexString.fromText('signed'):d.context.obj({}));const b=await d.save({updateFieldAppearances:false});assert.equal((await formDesignCreateAvailability(b)).createFormField,false,key);assert.equal((await inspectDesignWidgets(b)).widgets[0]?.designEditable,false,key)}
})

test('empty signature refuses forged identity and shared refs before writing and supports legacy required intent',async()=>{
 const r=await signature(),w=(await inspectDesignWidgets(r.bytes)).widgets[0],sha=hash(r.bytes)
 for(const extra of [{widgetId:'999R'},{widgetIdentity:'0'.repeat(64)},{expectedWidgetSha256:'0'.repeat(64)}])await assert.rejects(editDesignWidget(r.bytes,sha,{kind:'editFormWidget',sourceSha256:sha,...target(w),...extra,required:true}))
 const changed=await editDesignFieldRequired(r.bytes,sha,{kind:'editFormFieldRequired',sourceSha256:sha,...target(w),required:true});assert.deepEqual(changed.skippedOperations,[])
 const d=await PDFDocument.load(r.bytes);d.catalog.set(PDFName.of('UnexpectedAlias'),d.getForm().getField('Signature1').ref);const shared=await d.save({updateFieldAppearances:false});assert.equal((await formDesignCreateAvailability(shared)).createFormField,false);assert.equal((await inspectDesignWidgets(shared)).widgets[0].designEditable,false)
})
test('signature design refuses shared AcroForm Fields and page Annots containers',async()=>{
 const r=await signature()
 for(const container of ['Annots','Fields','AcroForm']){
  const d=await PDFDocument.load(r.bytes),owner=container==='Annots'?d.getPage(0).node:container==='Fields'?d.getForm().acroForm.dict:d.catalog,key=PDFName.of(container),raw=owner.get(key)!,ref=raw instanceof PDFRef?raw:d.context.register(d.context.lookup(raw))
  owner.set(key,ref);d.catalog.set(PDFName.of('PreserveAlias'),ref);const b=await d.save({updateFieldAppearances:false}),w=(await inspectDesignWidgets(b)).widgets[0]
  assert.equal((await formDesignCreateAvailability(b)).createFormField,false,container);assert.equal(w.designEditable,false,container);assert.equal(w.removable,false,container);await assert.rejects(removeDesignWidgetWithReceipt(b,hash(b),target(w)))
 }
})
