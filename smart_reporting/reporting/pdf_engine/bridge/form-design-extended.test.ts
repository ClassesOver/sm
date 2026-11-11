import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFName,PDFDict,PDFTextField,PDFRadioGroup,PDFDropdown} from 'pdf-lib'
import {createDesignField,formDesignCreateAvailability} from './form-design-create'
import {inspectDesignWidgets} from './form-design'
import {editDesignWidget,arrangeDesignWidgets} from './form-design-properties'
const hash=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex')
const fixture=()=>readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url))
const identity=(bytes:Uint8Array)=>({sourceSha256:hash(bytes),pageId:'sha256:'+hash(bytes)+':page:0'})
function op(bytes:Uint8Array,fieldKind:string,extra:Record<string,unknown>={}){return {kind:'createFormField',...identity(bytes),fieldName:'customer',fieldKind,rect:[30,180,150,204],required:true,...extra} as any}
const target=(w:any)=>({fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256})
test('creates date and choice with actual options values and exact built-in date actions reusable after reopen',async()=>{
 for(const kind of ['date','choice']){const bytes=await fixture(),r=await createDesignField(bytes,hash(bytes),op(bytes,kind,kind==='date'?{dateFormat:'yyyy-mm-dd',value:'2026-11-11'}:{options:['One','Two'],value:'Two'}));assert.deepEqual(r.skippedOperations,[]);const d=await PDFDocument.load(r.bytes),f=d.getForm().getField('customer');assert.equal(f.isRequired(),true);if(kind==='date'){assert.ok(f instanceof PDFTextField);assert.equal(f.getText(),'2026-11-11');assert.ok(f.acroField.dict.lookupMaybe(PDFName.of('AA'),PDFDict));assert.equal((await formDesignCreateAvailability(r.bytes)).createFormField,true)}else{assert.ok(f instanceof PDFDropdown);assert.deepEqual(f.getOptions(),['One','Two']);assert.deepEqual(f.getSelected(),['Two'])}}
})
test('creates one atomic radio group with multiple real widgets and exactly one initial selection',async()=>{
 const bytes=await fixture(),i=identity(bytes),r=await createDesignField(bytes,hash(bytes),op(bytes,'radio',{radioWidgets:[{pageId:i.pageId,rect:[30,180,150,204],exportValue:'Yes',checked:true},{pageId:i.pageId,rect:[30,140,150,164],exportValue:'No'}]}));assert.deepEqual(r.skippedOperations,[]);const f=(await PDFDocument.load(r.bytes)).getForm().getRadioGroup('customer');assert.ok(f instanceof PDFRadioGroup);assert.deepEqual(f.getOptions(),['Yes','No']);assert.equal(f.getSelected(),'Yes');assert.equal(f.acroField.getWidgets().length,2);const census=await inspectDesignWidgets(r.bytes);assert.equal(census.widgets.length,2);assert.ok(census.widgets.every(w=>w.designEditable&&!w.removable));assert.equal((await formDesignCreateAvailability(r.bytes)).createFormField,true)
})
test('exact widget rectangle and required edits preserve other widgets and do not allow field-name fallback',async()=>{
 const bytes=await fixture(),r=await createDesignField(bytes,hash(bytes),op(bytes,'text')),w=(await inspectDesignWidgets(r.bytes)).widgets[0];const edit={kind:'editFormWidget' as const,sourceSha256:hash(r.bytes),...target(w),rect:[50,170,170,194] as [number,number,number,number],required:false};const changed=await editDesignWidget(r.bytes,hash(r.bytes),edit);assert.deepEqual(changed.skippedOperations,[]);const field=(await PDFDocument.load(changed.bytes)).getForm().getTextField('customer');assert.equal(field.isRequired(),false);assert.deepEqual((await inspectDesignWidgets(changed.bytes)).widgets[0].rect,edit.rect);await assert.rejects(editDesignWidget(r.bytes,hash(r.bytes),{...edit,widgetId:'999R'}))
})
test('same-page arrangement uses exact targets and preserves original field values',async()=>{
 const bytes=await fixture(),first=await createDesignField(bytes,hash(bytes),op(bytes,'text',{value:'Alice'})),second=await createDesignField(first.bytes,hash(first.bytes),op(first.bytes,'text',{fieldName:'other',rect:[80,100,200,124],value:'Bob'})),widgets=(await inspectDesignWidgets(second.bytes)).widgets;const r=await arrangeDesignWidgets(second.bytes,hash(second.bytes),{kind:'arrangeFormWidgets',sourceSha256:hash(second.bytes),targets:widgets.map(target),alignment:'left'});assert.deepEqual(r.skippedOperations,[]);assert.deepEqual((await inspectDesignWidgets(r.bytes)).widgets.map(w=>w.rect[0]),[30,30]);const out=await PDFDocument.load(r.bytes);assert.equal(out.getForm().getTextField('customer').getText(),'Alice');assert.equal(out.getForm().getTextField('other').getText(),'Bob')
})
