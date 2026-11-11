import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFDict,PDFName} from 'pdf-lib'
import {createDesignField} from './form-design-create'
const hash=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
const fixture=()=>readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url))
function operation(bytes:Uint8Array,kind:'text'|'checkbox'){return {kind:'createFormField' as const,sourceSha256:hash(bytes),pageId:'sha256:'+hash(bytes)+':page:0',fieldName:'customer',fieldKind:kind,rect:[30,180,150,204] as [number,number,number,number],required:true,...(kind==='checkbox'?{checked:true}:{})}}
test('reportlab real three-page source keeps original resources and body when creating text and checkbox',async()=>{
 const bytes=await fixture()
 for(const kind of ['text','checkbox'] as const){const result=await createDesignField(bytes,hash(bytes),operation(bytes,kind));assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0]);const out=await PDFDocument.load(result.bytes);assert.equal(out.getPageCount(),3);assert.equal(out.getForm().getField('customer').isRequired(),true)}
})
test('reportlab resource mapping tampering remains a warning and retains actual generated PDF bytes',async()=>{
 const bytes=await fixture(),original=PDFDocument.prototype.save
 PDFDocument.prototype.save=async function(options){const fonts=this.getPage(0).node.Resources()?.lookupMaybe(PDFName.of('Font'),PDFDict);fonts?.set(PDFName.of('F1'),PDFName.of('ForgedFont'));return original.call(this,options)}
 try{const result=await createDesignField(bytes,hash(bytes),operation(bytes,'text'));assert.deepEqual(result.appliedOperationIndices,[]);assert.equal(result.skippedOperations.length,1);assert.match(result.skippedOperations[0].reason,/pdf_form_create_output_review_failed/);assert.ok(result.bytes.length>0);assert.equal(result.sha256,hash(result.bytes));assert.equal((await PDFDocument.load(result.bytes)).getForm().getTextField('customer').isRequired(),true)}finally{PDFDocument.prototype.save=original}
})
