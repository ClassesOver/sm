import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,PDFArray,PDFDict,PDFCheckBox,PDFTextField,PDFNumber,degrees} from 'pdf-lib'
import {createDesignField,editDesignFieldRequired,formDesignCreateAvailability} from './form-design-create'
import {inspectDesignWidgets} from './form-design'
import {createHash} from 'node:crypto'
const hash=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
async function fixture(){const d=await PDFDocument.create();d.addPage([300,400]).drawText('surviving body',{x:20,y:350});return d.save()}
function op(bytes:Uint8Array,kind:'text'|'checkbox'='text'){return {kind:'createFormField' as const,sourceSha256:hash(bytes),pageId:'sha256:'+hash(bytes)+':page:0',fieldName:'customer',fieldKind:kind,rect:[30,180,150,204] as [number,number,number,number],required:true,...(kind==='checkbox'?{checked:true}:{})}}
test('creates real text and checkbox widgets with appearance and deterministic receipt',async()=>{
 for(const kind of ['text','checkbox']as const){const bytes=await fixture(),operation=op(bytes,kind),r=await createDesignField(bytes,hash(bytes),operation),d=await PDFDocument.load(r.bytes),field=d.getForm().getField('customer');assert.equal(field.isRequired(),true);assert.equal(field instanceof PDFTextField,kind==='text');assert.equal(field instanceof PDFCheckBox,kind==='checkbox');if(field instanceof PDFCheckBox)assert.equal(field.isChecked(),true);const widget=field.acroField.getWidgets()[0];assert.ok(widget.dict.lookupMaybe(PDFName.of('AP'),PDFDict));assert.equal(d.getPage(0).node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.size(),1);assert.deepEqual(r.appliedOperationIndices,[0],JSON.stringify(r.skippedOperations));assert.deepEqual(r.skippedOperations,[]);assert.equal(r.sha256,hash(r.bytes));assert.equal((await createDesignField(bytes,hash(bytes),operation)).previewDigest,r.previewDigest)}
})
test('keeps existing fields and edits only the exact required flag without fallback',async()=>{
 const source=await fixture(),first=await createDesignField(source,hash(source),op(source)),target=(await inspectDesignWidgets(first.bytes)).widgets[0];assert.equal(target.removable,true)
 const edit={kind:'editFormFieldRequired' as const,sourceSha256:hash(first.bytes),fieldName:target.fieldName,widgetId:target.widgetId,widgetIdentity:target.widgetIdentity,expectedWidgetSha256:target.expectedWidgetSha256,required:false}
 const changed=await editDesignFieldRequired(first.bytes,hash(first.bytes),edit);assert.equal((await PDFDocument.load(changed.bytes)).getForm().getField('customer').isRequired(),false);assert.deepEqual(changed.skippedOperations,[])
 const second=await createDesignField(first.bytes,hash(first.bytes),{...op(first.bytes,'checkbox'),fieldName:'consent'});assert.deepEqual((await PDFDocument.load(second.bytes)).getForm().getFields().map(f=>f.getName()),['customer','consent'])
 await assert.rejects(editDesignFieldRequired(first.bytes,hash(first.bytes),{...edit,widgetId:'999R'}));await assert.rejects(editDesignFieldRequired(first.bytes,hash(first.bytes),{...edit,expectedWidgetSha256:'0'.repeat(64)}))
})
test('rejects forged source duplicate names geometry and unsafe sources',async()=>{
 const bytes=await fixture(),operation=op(bytes)
 for(const extra of [{sourceSha256:'0'.repeat(64)},{pageId:'bad'},{fieldName:'a..b'},{fieldName:'  '},{fieldKind:'signature'},{rect:[0,0,0,0]},{rect:[-2,0,20,20]},{checked:true}])await assert.rejects(createDesignField(bytes,hash(bytes),{...operation,...extra}))
 const first=await createDesignField(bytes,hash(bytes),operation);await assert.rejects(createDesignField(first.bytes,hash(first.bytes),op(first.bytes)))
 for(const mode of ['signature','xfa','unit','action']){const d=await PDFDocument.load(bytes);if(mode==='signature')d.catalog.set(PDFName.of('Perms'),d.context.obj({}));if(mode==='xfa')d.getForm().acroForm.dict.set(PDFName.of('XFA'),d.context.obj([]));if(mode==='unit')d.getPage(0).node.set(PDFName.of('UserUnit'),PDFNumber.of(2));if(mode==='action')d.catalog.set(PDFName.of('OpenAction'),d.context.obj({S:'JavaScript'}));const content=await d.save();assert.equal((await formDesignCreateAvailability(content)).createFormField,false);await assert.rejects(createDesignField(content,hash(content),op(content)))}
})
test('preserves crop and rotation when adding widgets on rotated pages',async()=>{
 for(const angle of [0,90,180,270]){const d=await PDFDocument.load(await fixture());d.getPage(0).setCropBox(10,15,280,370);d.getPage(0).setRotation(degrees(angle));const bytes=await d.save(),result=await createDesignField(bytes,hash(bytes),op(bytes,'checkbox')),out=await PDFDocument.load(result.bytes);assert.deepEqual(result.skippedOperations,[]);assert.equal(out.getPage(0).getRotation().angle,angle);assert.deepEqual(out.getPage(0).getCropBox(),{x:10,y:15,width:280,height:370});assert.equal(out.getForm().getCheckBox('customer').isChecked(),true)}
})
