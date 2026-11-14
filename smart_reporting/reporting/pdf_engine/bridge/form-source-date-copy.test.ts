import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDict,PDFDocument,PDFName,PDFString} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {FORM_DATE_FORMATS,inspectDesignDateActions} from './form-design-actions'
import {bodySnapshot,fieldSnapshot} from './form-design-create'
async function fixture(){
 const d=await PDFDocument.create();d.addPage([400,500]).drawText('Original dates',{x:30,y:450});d.addPage([400,500]);const empty=await d.save(),m=await inspectPdf(empty)
 const ops=FORM_DATE_FORMATS.map((format,i)=>({kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,fieldName:'Date'+i,fieldKind:'date',rect:[30,360-i*50,190,384-i*50],required:i===0,value:['2026-11-14','11/14/2026','14/11/2026','2026/11/14'][i],dateFormat:format}))
 const source=await patchPdfWithReceipt(empty,ops,sha256(empty));assert.deepEqual(source.skippedOperations,[])
 const out=await PDFDocument.load(source.bytes,{updateMetadata:false})
 for(const[i,f]of out.getForm().getFields().entries()){
  f.acroField.dict.set(PDFName.of('DV'),PDFString.of(['2025-01-02','01/02/2025','02/01/2025','2025/01/02'][i]!))
  const aa=f.acroField.dict.lookup(PDFName.of('AA'),PDFDict);for(const key of aa.keys())aa.set(key,out.context.register(aa.lookup(key,PDFDict)));f.acroField.dict.set(PDFName.of('AA'),out.context.register(aa))
 }
 return out.save({useObjectStreams:false,updateFieldAppearances:false})
}
async function operations(bytes:Uint8Array){const m=await inspectPdf(bytes);return m.formDesignWidgets.map(w=>({kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[1]!.pageId,fieldName:w.fieldName+'_copy1',fieldKind:'date',rect:[w.rect[0]+10,w.rect[1]-10,w.rect[2]+10,w.rect[3]-10],required:w.required,copyFrom:{fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256}}))}
test('copies all four exact date formats across pages retaining private actions values defaults and appearances',async()=>{
 const bytes=await fixture(),m=await inspectPdf(bytes);assert.ok(m.formDesignWidgets.every(w=>w.copyEditable===true))
 const before=await PDFDocument.load(bytes),result=await patchPdfWithReceipt(bytes,await operations(bytes),sha256(bytes)),out=await PDFDocument.load(result.bytes)
 assert.deepEqual(result.appliedOperationIndices,[0,1,2,3]);assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(bodySnapshot(out),bodySnapshot(before));assert.deepEqual(fieldSnapshot(out).filter(row=>!String(row[1]).includes('_copy1')),fieldSnapshot(before))
 for(const[i,format]of FORM_DATE_FORMATS.entries()){
  const source=out.getForm().getTextField('Date'+i),clone=out.getForm().getTextField('Date'+i+'_copy1'),a=source.acroField.dict.lookup(PDFName.of('AA'),PDFDict),b=clone.acroField.dict.lookup(PDFName.of('AA'),PDFDict)
  assert.equal(inspectDesignDateActions(clone.acroField.dict)?.format,format);assert.notEqual(String(source.acroField.dict.get(PDFName.of('AA'))),String(clone.acroField.dict.get(PDFName.of('AA'))))
  for(const key of ['F','K']){assert.notEqual(String(a.get(PDFName.of(key))),String(b.get(PDFName.of(key))));assert.equal(a.lookup(PDFName.of(key),PDFDict).toString(),b.lookup(PDFName.of(key),PDFDict).toString())}
  for(const key of ['V','DV','DA','Ff'])assert.equal(String(source.acroField.dict.get(PDFName.of(key))),String(clone.acroField.dict.get(PDFName.of(key))))
  assert.equal(String(clone.acroField.getWidgets()[0]!.dict.get(PDFName.of('P'))),String(out.getPage(1).ref));assert.notEqual(String(source.acroField.getWidgets()[0]!.dict.get(PDFName.of('AP'))),String(clone.acroField.getWidgets()[0]!.dict.get(PDFName.of('AP'))))
 }
 const original=out.getForm().getTextField('Date0').acroField.dict.toString();out.getForm().getTextField('Date0_copy1').setText('2027-02-03');const filled=await PDFDocument.load(await out.save());assert.equal(filled.getForm().getTextField('Date0').acroField.dict.toString(),original);assert.equal(inspectDesignDateActions(filled.getForm().getTextField('Date0_copy1').acroField.dict)?.format,'yyyy-mm-dd')
})
test('date copies reject script payloads and format overrides before any save',async(t)=>{
 const bytes=await fixture(),ops=await operations(bytes),save=PDFDocument.prototype.save;let writes=0;t.mock.method(PDFDocument.prototype,'save',async function(...args:Parameters<typeof save>){writes++;return save.apply(this,args)})
 for(const patch of [{dateFormat:'yyyy/mm/dd'},{script:'alert(1)'},{value:'forged'},{copyFrom:{...ops[1]!.copyFrom,widgetIdentity:'0'.repeat(64)}}])await assert.rejects(patchPdfWithReceipt(bytes,[ops[0],{...ops[1],...patch}],sha256(bytes)))
 assert.equal(writes,0)
})
test('noncanonical date actions never acquire source copy capability',async()=>{
 for(const script of ['AFDate_FormatEx("yyyy-mm-dd"); alert(1);','AFDate_FormatEx("yyyy");']){
  const d=await PDFDocument.load(await fixture()),aa=d.getForm().getTextField('Date0').acroField.dict.lookup(PDFName.of('AA'),PDFDict);aa.lookup(PDFName.of('F'),PDFDict).set(PDFName.of('JS'),PDFString.of(script));const bytes=await d.save({updateFieldAppearances:false}),model=await inspectPdf(bytes)
  assert.equal(model.formDesignWidgets.find(w=>w.fieldName==='Date0')!.copyEditable,false);await assert.rejects(patchPdfWithReceipt(bytes,[(await operations(bytes))[0]],sha256(bytes)))
 }
})
test('canonical date scripts do not grant date-copy permission to non-text fields or mismatched widget formats',async()=>{
 const d=await PDFDocument.load(await fixture()),date=d.getForm().getTextField('Date0'),checkbox=d.getForm().createCheckBox('Control');checkbox.addToPage(d.getPage(0),{x:250,y:200,width:20,height:20});checkbox.acroField.dict.set(PDFName.of('AA'),date.acroField.dict.get(PDFName.of('AA'))!)
 const other=d.getForm().getTextField('Date1').acroField.dict.get(PDFName.of('AA'))!;date.acroField.getWidgets()[0]!.dict.set(PDFName.of('AA'),other)
 const bytes=await d.save({updateFieldAppearances:false}),model=await inspectPdf(bytes)
 assert.equal(model.formDesignWidgets.find(w=>w.fieldName==='Control')!.copyEditable,false);assert.equal(model.formDesignWidgets.find(w=>w.fieldName==='Date0')!.copyEditable,false)
})
