import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFDict,PDFName} from 'pdf-lib'
import {createDesignField,formDesignCreateAvailability,bodySnapshot} from './form-design-create'
import {inspectDesignWidgets,formDesignTreeSafe} from './form-design'
const hash=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex'),fixture=()=>readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url))
function op(b:Uint8Array,name:string){return {kind:'createFormField' as const,sourceSha256:hash(b),pageId:'sha256:'+hash(b)+':page:0',fieldName:name,fieldKind:'text' as const,rect:[30,180,150,204] as [number,number,number,number],required:true,value:'Alice'}}
test('creates and reuses canonical fully qualified pdf-lib field parents without shared aliases',async()=>{
 const source=await fixture();let bytes:Uint8Array=source
 for(const name of ['party.customer.name','party.customer.code','party.vendor.name']){const r=await createDesignField(bytes,hash(bytes),op(bytes,name));assert.deepEqual(r.skippedOperations,[]);bytes=r.bytes;const d=await PDFDocument.load(bytes);assert.equal(formDesignTreeSafe(d),true);assert.equal(d.getForm().getTextField(name).getText(),'Alice');assert.equal((await formDesignCreateAvailability(bytes)).createFormField,true)}
 const d=await PDFDocument.load(bytes);assert.deepEqual(d.getForm().getFields().map(f=>f.getName()),['party.customer.name','party.customer.code','party.vendor.name']);assert.deepEqual(bodySnapshot(d),bodySnapshot(await PDFDocument.load(source)));assert.ok((await inspectDesignWidgets(bytes)).widgets.every(w=>w.designEditable&&!w.removable))
})
test('rejects duplicate terminal prefixes empty segments and excessive name depth',async()=>{
 const source=await fixture(),first=await createDesignField(source,hash(source),op(source,'party.customer'))
 for(const name of ['party.customer','party','party.customer.detail','party..code','.party','party.','a.'.repeat(16)+'b','a'.repeat(65)])await assert.rejects(createDesignField(first.bytes,hash(first.bytes),op(first.bytes,name)))
})
test('does not repair preexisting duplicate registration aliases from raw pdf-lib hierarchy sources',async()=>{
 const d=await PDFDocument.load(await fixture()),f=d.getForm().createTextField('party.customer');f.addToPage(d.getPage(0));const b=await d.save();assert.equal((await formDesignCreateAvailability(b)).createFormField,false)
})
test('hierarchy postwrite tree corruption keeps actual output identity and warning',async()=>{
 const b=await fixture(),save=PDFDocument.prototype.save
 PDFDocument.prototype.save=async function(options){for(const[,dict]of this.context.enumerateIndirectObjects())if(dict instanceof PDFDict&&dict.has(PDFName.of('Kids'))&&!dict.has(PDFName.of('FT'))&&dict.has(PDFName.of('T')))dict.set(PDFName.of('TU'),PDFName.of('ForgedParent'));return save.call(this,options)}
 try{const r=await createDesignField(b,hash(b),op(b,'party.customer'));assert.ok(r.bytes.length);assert.equal(r.sha256,hash(r.bytes));assert.deepEqual(r.appliedOperationIndices,[]);assert.match(r.skippedOperations[0].reason,/pdf_form_create_output_review_failed/)}finally{PDFDocument.prototype.save=save}
})
