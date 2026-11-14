import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDict,PDFDocument,PDFName,PDFRef,PDFArray,PDFStream} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {bodySnapshot,fieldSnapshot} from './form-design-create'
async function fixture(selected=true,cross=false,name='Answer'){
 const d=await PDFDocument.create();d.addPage([400,500]).drawText('Original radio',{x:30,y:450});d.addPage([400,500]);const empty=await d.save(),m=await inspectPdf(empty)
 const result=await patchPdfWithReceipt(empty,[{kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[0]!.pageId,fieldName:name,fieldKind:'radio',rect:[30,300,50,320],required:true,radioWidgets:['Yes','No','Maybe'].map((exportValue,i)=>({pageId:m.pages[cross&&i===2?1:0]!.pageId,rect:[30+i*60,300,50+i*60,320],exportValue,checked:selected&&i===1}))}],sha256(empty));assert.deepEqual(result.skippedOperations,[])
 const out=await PDFDocument.load(result.bytes),group=out.getForm().getRadioGroup(name);group.acroField.dict.set(PDFName.of('DV'),group.acroField.getOnValues()[0]!);return out.save({useObjectStreams:false,updateFieldAppearances:false})
}
async function operation(bytes:Uint8Array,name='Answer'){const m=await inspectPdf(bytes),group=m.formDesignWidgets.filter(w=>w.fieldName===name),w=group[0]!,radioWidgets=group.map((w,i)=>({pageId:m.pages[1]!.pageId,rect:w.rect.map((v,j)=>v+(j%2===0?10:-10)),exportValue:w.radioOptions![i]!,checked:w.radioChecked===true}));return {kind:'createFormField',sourceSha256:m.sourceSha256,pageId:m.pages[1]!.pageId,fieldName:name+'_copy1',fieldKind:'radio',rect:radioWidgets[0]!.rect,required:true,copyFrom:{fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256},radioWidgets}}
function appearance(d:PDFDocument,name:string){const stack:unknown[]=d.getForm().getRadioGroup(name).acroField.getWidgets().map(w=>w.dict.get(PDFName.of('AP'))),seen=new Set<object>(),result:string[]=[];while(stack.length){let v=stack.pop();if(v instanceof PDFRef)v=d.context.lookup(v);if(v&&typeof v==='object'){if(seen.has(v))continue;seen.add(v)}if(v instanceof PDFStream){result.push(v.dict.toString()+Buffer.from(v.getContents()).toString('base64'));v=v.dict}if(v instanceof PDFDict)stack.push(...v.values());else if(v instanceof PDFArray)stack.push(...v.asArray());else result.push(String(v))}return result}
test('copies whole selected and unselected source radio groups preserving defaults AP hierarchy and later fill isolation',async()=>{
 for(const selected of [true,false]){
  const bytes=await fixture(selected),m=await inspectPdf(bytes);assert.ok(m.formDesignWidgets.every(w=>w.copyEditable))
  const op=await operation(bytes),before=await PDFDocument.load(bytes),result=await patchPdfWithReceipt(bytes,[op],sha256(bytes)),out=await PDFDocument.load(result.bytes),source=out.getForm().getRadioGroup('Answer'),clone=out.getForm().getRadioGroup('Answer_copy1')
  assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(bodySnapshot(out),bodySnapshot(before));assert.deepEqual(fieldSnapshot(out,'Answer_copy1'),fieldSnapshot(before))
  assert.deepEqual(clone.getOptions(),['Yes','No','Maybe']);assert.equal(clone.getSelected(),selected?'No':undefined);assert.equal(clone.isRequired(),true);for(const key of ['V','DV','Ff','Opt'])assert.equal(String(clone.acroField.dict.get(PDFName.of(key))),String(source.acroField.dict.get(PDFName.of(key))))
  const widgetIds=(await inspectPdf(result.bytes)).formDesignWidgets.filter(w=>w.fieldName==='Answer_copy1');assert.deepEqual(widgetIds.map(w=>w.pageIndex),[1,1,1]);assert.deepEqual(widgetIds.map(w=>w.rect),op.radioWidgets.map(w=>w.rect));assert.ok(widgetIds.every(w=>w.copyEditable))
  for(const[i,w]of clone.acroField.getWidgets().entries()){const original=source.acroField.getWidgets()[i]!;assert.equal(String(w.dict.get(PDFName.of('AS'))),String(original.dict.get(PDFName.of('AS'))));assert.notEqual(String(w.dict.get(PDFName.of('AP'))),String(original.dict.get(PDFName.of('AP'))))}
  const original=fieldSnapshot(out,'Answer_copy1'),ap=appearance(out,'Answer');clone.select('Maybe');const next=await PDFDocument.load(await out.save());assert.deepEqual(fieldSnapshot(next,'Answer_copy1'),original);assert.deepEqual(appearance(next,'Answer'),ap);assert.equal(next.getForm().getRadioGroup('Answer').getSelected(),selected?'No':undefined)
 }
})
test('all radio copy source members layout and choice states preflight before any write',async(t)=>{
 const bytes=await fixture(),op=await operation(bytes),save=PDFDocument.prototype.save;let writes=0;t.mock.method(PDFDocument.prototype,'save',async function(...args:Parameters<typeof save>){writes++;return save.apply(this,args)})
 for(const patch of [
  {radioWidgets:op.radioWidgets.slice(0,2)},
  {radioWidgets:op.radioWidgets.map((w,i)=>i===1?{...w,checked:false}:w)},
  {radioWidgets:op.radioWidgets.map((w,i)=>i===1?{...w,exportValue:'Forged'}:w)},
  {radioWidgets:op.radioWidgets.map((w,i)=>i===1?{...w,rect:w.rect.map((v,j)=>j===0?v+1:v)}:w)},
  {radioWidgets:op.radioWidgets.map((w,i)=>i===1?{...w,pageId:'forged'}:w)},
  {copyFrom:{...op.copyFrom,widgetIdentity:'0'.repeat(64)}},
 ])await assert.rejects(patchPdfWithReceipt(bytes,[op,{...op,fieldName:'Answer_copy2',...patch}],sha256(bytes)))
 assert.equal(writes,0)
})
test('collapsed cross-page copies and malformed source radio groups remain rejected',async()=>{
 const cross=await fixture(true,true);assert.ok((await inspectPdf(cross)).formDesignWidgets.every(w=>w.copyEditable));await assert.rejects(patchPdfWithReceipt(cross,[await operation(cross)],sha256(cross)))
 for(const mode of ['sharedAP','badAS','badP','unison']){
  const d=await PDFDocument.load(await fixture()),group=d.getForm().getRadioGroup('Answer'),widgets=group.acroField.getWidgets()
  if(mode==='sharedAP')widgets[1]!.dict.set(PDFName.of('AP'),widgets[0]!.dict.get(PDFName.of('AP'))!);else if(mode==='badAS')widgets[0]!.dict.set(PDFName.of('AS'),PDFName.of('Fake'));else if(mode==='badP')widgets[1]!.dict.set(PDFName.of('P'),d.getPage(1).ref);else group.disableMutualExclusion()
  const bytes=await d.save({updateFieldAppearances:false});assert.ok((await inspectPdf(bytes)).formDesignWidgets.every(w=>!w.copyEditable),mode);await assert.rejects(patchPdfWithReceipt(bytes,[await operation(bytes)],sha256(bytes)))
 }
})
test('multiple hierarchical radio copies preserve parent tree and original operation indices',async()=>{
 const bytes=await fixture(true,false,'party.Answer'),first=await operation(bytes,'party.Answer'),second={...first,fieldName:'party.Answer_copy2',pageId:'sha256:'+sha256(bytes)+':page:0',radioWidgets:first.radioWidgets.map(row=>({...row,pageId:'sha256:'+sha256(bytes)+':page:0',rect:row.rect.map((v,i)=>v+(i%2===0?10:-10))}))};second.rect=second.radioWidgets[0]!.rect
 const result=await patchPdfWithReceipt(bytes,[first,second],sha256(bytes)),out=await PDFDocument.load(result.bytes);assert.deepEqual(result.appliedOperationIndices,[0,1]);assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(out.getForm().getFields().map(f=>f.getName()),['party.Answer','party.Answer_copy1','party.Answer_copy2']);assert.equal(out.getForm().getRadioGroup('party.Answer_copy2').getSelected(),'No');assert.deepEqual((await inspectPdf(result.bytes)).formDesignWidgets.filter(w=>w.fieldName==='party.Answer_copy2').map(w=>w.pageIndex),[0,0,0])
})
test('postwrite radio review faults preserve the actual copied group and honest warning',async(t)=>{
 const bytes=await fixture(),op=await operation(bytes),load=PDFDocument.load
 t.mock.method(PDFDocument,'load',async function(input:Parameters<typeof load>[0],options:Parameters<typeof load>[1]){if(input instanceof Uint8Array&&sha256(input)!==sha256(bytes))throw Error('injected radio review');return load.call(PDFDocument,input,options)})
 const result=await patchPdfWithReceipt(bytes,[op],sha256(bytes));t.mock.restoreAll();assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/output_review_failed.*injected radio review/);const out=await PDFDocument.load(result.bytes);assert.equal(out.getForm().getRadioGroup('Answer_copy1').getSelected(),'No');assert.equal(out.getForm().getRadioGroup('Answer_copy1').acroField.getWidgets().length,3)
})
