import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDict,PDFDocument,PDFName,PDFRawStream,PDFRef,PDFStream,PDFArray,PDFString,StandardFonts} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {bodySnapshot,fieldSnapshot} from './form-design-create'
async function fixture(){
 const d=await PDFDocument.create(),p=d.addPage([400,500]);p.drawText('Original stays',{x:30,y:450});d.addPage([400,500])
 const font=await d.embedFont(StandardFonts.TimesRomanBoldItalic),f=d.getForm(),t=f.createTextField('customer.name');t.setText('Alice');t.enableRequired();t.addToPage(p,{x:30,y:300,width:160,height:25,font});t.acroField.dict.set(PDFName.of('DV'),PDFString.of('Default name'))
 const c=f.createCheckBox('customer.agree');c.addToPage(p,{x:30,y:250,width:20,height:20});c.check()
 const select=f.createDropdown('customer.choice');select.addOptions(['A','B']);select.select('B');select.addToPage(p,{x:30,y:200,width:160,height:25,font});select.acroField.dict.set(PDFName.of('DV'),PDFString.of('A'))
 const all=d.context.enumerateIndirectObjects(),canonical=new Set(f.acroForm.getAllFields().map(([,r])=>String(r)));for(const [r,o]of all)if(o instanceof PDFDict&&o.has(PDFName.of('Kids'))&&!o.has(PDFName.of('FT'))&&!canonical.has(String(r))&&all.some(([s,v])=>v===o&&canonical.has(String(s))))d.context.delete(r)
 return d.save({useObjectStreams:false,updateFieldAppearances:false})
}
function appearances(d:PDFDocument,name:string){const stack:unknown[]=d.getForm().getField(name).acroField.getWidgets().map(w=>w.dict.get(PDFName.of('AP'))),seen=new Set<object>(),result:string[]=[];while(stack.length){let value=stack.pop();if(value instanceof PDFRef)value=d.context.lookup(value);if(value&&typeof value==='object'){if(seen.has(value))continue;seen.add(value)}if(value instanceof PDFStream){result.push(value.dict.toString()+Buffer.from(value.getContents()).toString('base64'));value=value.dict}if(value instanceof PDFDict)stack.push(...value.values());else if(value instanceof PDFArray)stack.push(...value.asArray());else result.push(String(value))}return result}
async function copies(bytes:Uint8Array){const m=await inspectPdf(bytes);return m.formDesignWidgets.map(w=>({kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[1]!.pageId,fieldName:w.fieldName+'_copy1',fieldKind:w.fieldKind,rect:[w.rect[0]+10,w.rect[1]-10,w.rect[2]+10,w.rect[3]-10],required:w.required,copyFrom:{fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256}}))}
test('copies source fields retaining defaults font appearances hierarchy and isolation on later fill',async()=>{
 const bytes=await fixture(),before=await PDFDocument.load(bytes),operations=await copies(bytes),original=JSON.stringify(operations),result=await patchPdfWithReceipt(bytes,operations,sha256(bytes)),out=await PDFDocument.load(result.bytes),f=out.getForm()
 assert.deepEqual(result.appliedOperationIndices,[0,1,2]);assert.deepEqual(result.skippedOperations,[]);assert.equal(JSON.stringify(operations),original);assert.deepEqual(bodySnapshot(out),bodySnapshot(before));assert.deepEqual(fieldSnapshot(out).filter(row=>!String(row[1]).includes('_copy1')),fieldSnapshot(before))
 const textFont=(name:string)=>{const ap=f.getTextField(name).acroField.getWidgets()[0]!.dict.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'),PDFRawStream),fonts=ap.dict.lookup(PDFName.of('Resources'),PDFDict).lookup(PDFName.of('Font'),PDFDict);return fonts.values().map(ref=>String(out.context.lookup(ref,PDFDict).get(PDFName.of('BaseFont'))))};assert.deepEqual(textFont('customer.name'),['/Times-BoldItalic']);assert.deepEqual(textFont('customer.name_copy1'),textFont('customer.name'))
 assert.equal(f.getTextField('customer.name_copy1').getText(),'Alice');assert.equal(f.getTextField('customer.name_copy1').isRequired(),true);assert.equal(f.getCheckBox('customer.agree_copy1').isChecked(),true);assert.deepEqual(f.getDropdown('customer.choice_copy1').getSelected(),['B']);assert.deepEqual(f.getDropdown('customer.choice_copy1').getOptions(),['A','B'])
 for(const op of operations){const source=f.getField(op.copyFrom.fieldName),clone=f.getField(op.fieldName);for(const k of ['V','DV','DA','Ff','Opt'])assert.equal(String(clone.acroField.dict.get(PDFName.of(k))),String(source.acroField.dict.get(PDFName.of(k))));assert.notEqual(String(clone.ref),String(source.ref));const a=source.acroField.getWidgets()[0]!.dict,b=clone.acroField.getWidgets()[0]!.dict;assert.notEqual(String(b.get(PDFName.of('AP'))),String(a.get(PDFName.of('AP'))));assert.equal(String(b.get(PDFName.of('P'))),String(out.getPage(1).ref))}
 assert.ok((await inspectPdf(result.bytes)).formDesignWidgets.filter(w=>w.fieldName.endsWith('_copy1')).every(w=>w.designEditable&&w.pageIndex===1))
 const oldAppearance=appearances(out,'customer.name'),oldCheckAppearance=appearances(out,'customer.agree');const old=fieldSnapshot(out).filter(row=>!String(row[1]).includes('_copy1'));f.getTextField('customer.name_copy1').setText('Bob');f.getCheckBox('customer.agree_copy1').uncheck();const next=await PDFDocument.load(await out.save());assert.deepEqual(fieldSnapshot(next).filter(row=>!String(row[1]).includes('_copy1')),old);assert.deepEqual(appearances(next,'customer.name'),oldAppearance);assert.deepEqual(appearances(next,'customer.agree'),oldCheckAppearance);assert.equal(next.getForm().getTextField('customer.name').getText(),'Alice');assert.equal(next.getForm().getCheckBox('customer.agree').isChecked(),true)
})
test('all original copy identities and templates validate before any save',async(t)=>{
 const bytes=await fixture(),ops=await copies(bytes),save=PDFDocument.prototype.save;let writes=0;t.mock.method(PDFDocument.prototype,'save',async function(...args:Parameters<typeof save>){writes++;return save.apply(this,args)})
 for(const patch of [{copyFrom:{...ops[1]!.copyFrom,widgetIdentity:'0'.repeat(64)}},{required:true},{value:'forged'},{rect:[30,250,70,270]},{fieldKind:'radio'},{fieldName:'different.copy'},{copyFrom:{...ops[1]!.copyFrom,unknown:true}}])await assert.rejects(patchPdfWithReceipt(bytes,[ops[0],{...ops[1],...patch}],sha256(bytes)))
 assert.equal(writes,0)
})
test('source copy refuses unsupported auxiliary structures and does not promise unsafe copy capabilities',async()=>{
 for(const mutate of [
  (d:PDFDocument)=>d.getForm().getTextField('customer.name').acroField.dict.set(PDFName.of('AA'),d.context.obj({K:{S:'JavaScript',JS:PDFString.of('bad()')}})),
  (d:PDFDocument)=>d.getForm().getTextField('customer.name').acroField.getWidgets()[0]!.dict.set(PDFName.of('StructParent'),d.context.obj(1)),
  (d:PDFDocument)=>d.getForm().getTextField('customer.name').acroField.getWidgets()[0]!.dict.set(PDFName.of('MK'),d.context.obj({P:d.getPage(0).ref})),
 ]){
  const d=await PDFDocument.load(await fixture());mutate(d);const bytes=await d.save({updateFieldAppearances:false}),model=await inspectPdf(bytes),w=model.formDesignWidgets.find(w=>w.fieldName==='customer.name')!;assert.equal(w.copyEditable,false)
  await assert.rejects(patchPdfWithReceipt(bytes,[(await copies(bytes))[0]],sha256(bytes)))
 }
})
test('copy output-review failure retains generated PDF bytes and an honest skipped receipt',async(t)=>{
 const bytes=await fixture(),op=(await copies(bytes))[0]!,load=PDFDocument.load
 t.mock.method(PDFDocument,'load',async function(input:Parameters<typeof load>[0],options:Parameters<typeof load>[1]){if(input instanceof Uint8Array&&sha256(input)!==sha256(bytes))throw Error('injected copied-output review failure');return load.call(PDFDocument,input,options)})
 const result=await patchPdfWithReceipt(bytes,[op],sha256(bytes));t.mock.restoreAll()
 assert.notEqual(sha256(result.bytes),sha256(bytes));assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/pdf_form_copy_output_review_failed.*injected copied-output/);assert.equal((await PDFDocument.load(result.bytes)).getForm().getTextField('customer.name_copy1').getText(),'Alice')
})
test('does not advertise same-parent copying when the source parent path cannot form a valid new name',async()=>{
 const d=await PDFDocument.load(await fixture()),parent=d.getForm().getTextField('customer.name').acroField.dict.lookup(PDFName.of('Parent'),PDFDict);parent.set(PDFName.of('T'),PDFString.of('Contact details'))
 const bytes=await d.save({updateFieldAppearances:false}),widgets=(await inspectPdf(bytes)).formDesignWidgets
 assert.ok(widgets.length>0);assert.ok(widgets.every(w=>w.copyEditable===false&&w.copyReason?.includes('父层级')))
})
