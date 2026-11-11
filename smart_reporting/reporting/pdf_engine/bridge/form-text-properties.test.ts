import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFName,PDFDict,PDFRawStream,StandardFonts} from 'pdf-lib'
import {createDesignField,bodySnapshot,fieldSnapshot} from './form-design-create'
import {inspectDesignWidgets} from './form-design'
const hash=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex')
async function api(){const m=await import('./form-text-properties').catch(()=>null);assert.ok(m,'text property adapter is implemented');return m}
async function fixture(){let b:Uint8Array=await readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url));for(const[name,value,y]of [['party.customer.name','Alice',230],['party.customer.code','C001',180]]as const){b=(await createDesignField(b,hash(b),{kind:'createFormField',sourceSha256:hash(b),pageId:'sha256:'+hash(b)+':page:0',fieldName:name,fieldKind:'text',rect:[30,y,180,y+30],required:true,value})).bytes}return b}
async function op(bytes:Uint8Array){const w=(await inspectDesignWidgets(bytes)).widgets[0];return {kind:'editFormTextProperties' as const,sourceSha256:hash(bytes),fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256,multiLine:true,maxLen:32,textAlignment:'center' as const,fontSize:16}}
test('edits four text properties preserving values references other appearances and original body',async()=>{
 const m=await api(),bytes=await fixture(),d=await PDFDocument.load(bytes),original=d.getForm().getField('party.customer.name'),r=await m.editDesignTextProperties(bytes,hash(bytes),await op(bytes));assert.deepEqual(r.skippedOperations,[]);const out=await PDFDocument.load(r.bytes),f=out.getForm().getTextField('party.customer.name');assert.equal(f.getText(),'Alice');assert.equal(f.isMultiline(),true);assert.equal(f.getMaxLength(),32);assert.equal(f.getAlignment(),1);assert.equal(String(f.ref),String(original.ref));assert.deepEqual(f.acroField.Kids()!.asArray().map(String),original.acroField.Kids()!.asArray().map(String));assert.deepEqual(bodySnapshot(out),bodySnapshot(d));assert.deepEqual(fieldSnapshot(out,'party.customer.name'),fieldSnapshot(d,'party.customer.name'));const w=(await inspectDesignWidgets(r.bytes)).widgets[0];assert.equal(w.textPropertiesEditable,true);assert.equal(w.textProperties?.fontSize,16);assert.equal(w.textProperties?.fontName,'Helvetica');assert.equal(w.textProperties?.valueLength,5);assert.equal((await m.formTextPropertiesAvailability(r.bytes)).editFormTextProperties,true)
})
test('maxLen zero clears limit and shortening below existing value is refused without truncation',async()=>{
 const m=await api(),bytes=await fixture(),operation=await op(bytes)
 await assert.rejects(m.editDesignTextProperties(bytes,hash(bytes),{...operation,maxLen:4}),/length|长度/)
 for(const patch of [{fontSize:0},{multiLine:null},{textAlignment:'bad'},{rect:[30,230,180,260]},{widgetId:'999R'},{widgetIdentity:'0'.repeat(64)},{expectedWidgetSha256:'0'.repeat(64)}])await assert.rejects(m.editDesignTextProperties(bytes,hash(bytes),{...operation,...patch}as any))
 const r=await m.editDesignTextProperties(bytes,hash(bytes),{...operation,maxLen:0,multiLine:false,textAlignment:'right'}),f=(await PDFDocument.load(r.bytes)).getForm().getTextField(operation.fieldName);assert.deepEqual(r.skippedOperations,[]);assert.equal(f.getText(),'Alice');assert.equal(f.getMaxLength(),undefined);assert.equal(f.isMultiline(),false);assert.equal(f.getAlignment(),2)
})
test('per widget metadata refuses actions CJK custom fonts readonly and multiple widgets',async()=>{
 const m=await api(),bytes=await fixture()
 for(const mode of ['action','cjk','font','readonly','multi']){const d=await PDFDocument.load(bytes),f=d.getForm().getTextField('party.customer.name'),w=f.acroField.getWidgets()[0];if(mode==='action')f.acroField.dict.set(PDFName.of('AA'),d.context.obj({K:{S:'JavaScript',JS:'bad'}}));if(mode==='cjk')f.setText('中文');if(mode==='font'){const stream=w.dict.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'),PDFRawStream),fonts=stream.dict.lookup(PDFName.of('Resources'),PDFDict).lookup(PDFName.of('Font'),PDFDict);fonts.lookup(fonts.keys()[0],PDFDict).set(PDFName.of('BaseFont'),PDFName.of('CustomFont'))}if(mode==='readonly')f.enableReadOnly();if(mode==='multi')f.addToPage(d.getPage(1),{x:30,y:180,width:150,height:30});const bad=await d.save({updateFieldAppearances:false}),target=(await inspectDesignWidgets(bad)).widgets.find(w=>w.fieldName==='party.customer.name')!;assert.equal(target.textPropertiesEditable,false,mode);assert.ok(target.textPropertiesReason);await assert.rejects(m.editDesignTextProperties(bad,hash(bad),{...await op(bad),fontSize:14}))}
})
test('same standard Times face is retained instead of silently replacing it with Helvetica',async()=>{
 const m=await api(),d=await PDFDocument.load(await readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url))),f=d.getForm().createTextField('customer');f.setText('Alice');f.addToPage(d.getPage(0),{x:30,y:180,width:150,height:30,font:await d.embedFont(StandardFonts.TimesRoman)});const bytes=await d.save({updateFieldAppearances:false}),operation=await op(bytes),r=await m.editDesignTextProperties(bytes,hash(bytes),{...operation,fontSize:14});assert.deepEqual(r.skippedOperations,[]);assert.equal((await inspectDesignWidgets(r.bytes)).widgets[0].textProperties?.fontName,'Times-Roman')
})
test('postwrite unrelated field damage warns and retains actual output bytes identity',async()=>{
 const m=await api(),bytes=await fixture(),operation=await op(bytes),save=PDFDocument.prototype.save
 PDFDocument.prototype.save=async function(options){this.getForm().getTextField('party.customer.code').setText('Forged');return save.call(this,options)}
 try{const r=await m.editDesignTextProperties(bytes,hash(bytes),operation);assert.ok(r.bytes.length);assert.equal(r.sha256,hash(r.bytes));assert.deepEqual(r.appliedOperationIndices,[]);assert.match(r.skippedOperations[0].reason,/pdf_form_text_properties_output_review_failed/);assert.equal((await PDFDocument.load(r.bytes)).getForm().getTextField('party.customer.code').getText(),'Forged')}finally{PDFDocument.prototype.save=save}
})
