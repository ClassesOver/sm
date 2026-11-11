import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {writeFile,mkdir} from 'node:fs/promises'
import {PDFDocument,PDFDict,PDFName,PDFRawStream,PDFTextField,degrees} from 'pdf-lib'
import {inspectDesignWidgets} from './form-design'
import {arrangeDesignWidgets} from './form-design-properties'
import {arrangeDesignRects,FORM_ARRANGEMENTS} from './form-design-layout'
const sha=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex')
const id=(ref:unknown)=>String(ref).replace(/^(\d+) (\d+) R$/,(_,n,g)=>n+'R'+(g==='0'?'':g))
const target=(w:any)=>({fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256})
async function fixture(shared=false){
 const d=await PDFDocument.create();for(let i=0;i<3;i++){const p=d.addPage([400+i*30,500+i*30]);p.drawText('Original page '+i,{x:20,y:470});p.setCropBox(10,10,380+i*30,480+i*30);p.setRotation(degrees(i*90))}
 for(let page=0;page<3;page++)for(let i=0;i<(page===2?1:3);i++){const name=page===2&&shared?'p0f0':`p${page}f${i}`,f=(d.getForm().getFieldMaybe(name)as PDFTextField|undefined)??d.getForm().createTextField(name);f.addToPage(d.getPage(page),{x:30+i*70+page*15,y:80+i*80,width:40+i*10,height:20+i*5});f.setText(name)}
 return d.save({useObjectStreams:false})
}
function immutable(d:PDFDocument,ids:Set<string>){d.getPages();return d.context.enumerateIndirectObjects().map(([ref,o])=>[String(ref),ids.has(id(ref))&&o instanceof PDFDict?o.entries().filter(([k])=>!['/Rect','/AP'].includes(String(k))).map(([k,v])=>[String(k),String(v)]):o instanceof PDFRawStream?o.dict.toString()+Buffer.from(o.contents).toString('hex'):String(o)])}
async function setup(shared=false){const b=await fixture(shared),widgets=(await inspectDesignWidgets(b)).widgets;assert.equal(widgets.length,7);assert.ok(widgets.every(w=>w.designEditable));return {b,widgets,op:{kind:'arrangeFormWidgets' as const,sourceSha256:sha(b),targets:widgets.map(target),alignment:'left' as const}}}
test('all eleven modes arrange each page with its own crop rotation and anchor while leaving singleton untouched',async()=>{
 const {b,widgets,op}=await setup(),before=await PDFDocument.load(b,{updateMetadata:false})
 for(const alignment of FORM_ARRANGEMENTS){const r=await arrangeDesignWidgets(b,sha(b),{...op,alignment});assert.deepEqual(r.skippedOperations,[]);const after=await PDFDocument.load(r.bytes,{updateMetadata:false}),actual=(await inspectDesignWidgets(r.bytes)).widgets
  for(const pageIndex of [0,1]){const page=before.getPage(pageIndex),box=page.getCropBox(),selected=widgets.filter(w=>w.pageIndex===pageIndex),expected=arrangeDesignRects({pw:box.width,ph:box.height,x0:box.x,y0:box.y,rot:page.getRotation().angle},selected.map(w=>w.rect),alignment);assert.deepEqual(actual.filter(w=>w.pageIndex===pageIndex).map(w=>w.rect),expected,alignment+' page '+pageIndex)}
  assert.deepEqual(actual.map(w=>[w.widgetId,w.fieldName,w.pageIndex]),widgets.map(w=>[w.widgetId,w.fieldName,w.pageIndex]));for(const w of widgets)assert.equal(after.getForm().getTextField(w.fieldName).getText(),w.fieldName)
  const skipped=widgets.find(w=>w.pageIndex===2)!;assert.deepEqual(actual.find(w=>w.widgetId===skipped.widgetId)!.rect,skipped.rect);assert.equal(after.context.lookup(after.getForm().getTextField(skipped.fieldName).ref).toString(),before.context.lookup(before.getForm().getTextField(skipped.fieldName).ref).toString())
  const changed=new Set(widgets.filter(w=>w.pageIndex!==2).map(w=>w.widgetId)),originals=new Map(immutable(before,changed));for(const [ref,value]of immutable(after,changed))if(originals.has(ref))assert.deepEqual(value,originals.get(ref),alignment+' original '+ref)
 }
})
test('distribution skips a two-widget page and validates every skipped target before write',async()=>{
 const {b,widgets,op}=await setup(),selected=widgets.filter(w=>w.pageIndex!==1||w.fieldName!=='p1f2'),r=await arrangeDesignWidgets(b,sha(b),{...op,targets:selected.map(target),alignment:'distributeH'});assert.deepEqual(r.skippedOperations,[])
 const before=await PDFDocument.load(b,{updateMetadata:false}),after=await PDFDocument.load(r.bytes,{updateMetadata:false}),changed=new Set(widgets.filter(w=>w.pageIndex===0).map(w=>w.widgetId)),originals=new Map(immutable(before,changed));for(const[ref,value]of immutable(after,changed))if(originals.has(ref))assert.deepEqual(value,originals.get(ref),'untouched '+ref)
 for(const key of ['fieldName','widgetId','widgetIdentity','expectedWidgetSha256']){const targets=selected.map(target);targets.at(-1)![key as keyof typeof targets[number]]=key==='widgetId'?'999R':'f'.repeat(64);await assert.rejects(arrangeDesignWidgets(b,sha(b),{...op,targets,alignment:'distributeH'}),/identity|stale|readonly/)}
})
test('no eligible page is rejected without saving and old same-page operations remain supported',async()=>{
 const {b,widgets,op}=await setup();await assert.rejects(arrangeDesignWidgets(b,sha(b),{...op,targets:widgets.filter(w=>w.fieldName.endsWith('f0')).map(target)}),/每页/);await assert.rejects(arrangeDesignWidgets(b,sha(b),{...op,targets:widgets.filter(w=>!w.fieldName.endsWith('f2')).map(target),alignment:'distributeV'}),/每页/)
 const r=await arrangeDesignWidgets(b,sha(b),{...op,targets:widgets.filter(w=>w.pageIndex===0).map(target)});assert.deepEqual(r.skippedOperations,[])
})
test('skipped widget of a shared field keeps its exact appearance reference and raw stream',async()=>{
 const {b,widgets,op}=await setup(true),before=await PDFDocument.load(b,{updateMetadata:false}),r=await arrangeDesignWidgets(b,sha(b),op);assert.deepEqual(r.skippedOperations,[]);const after=await PDFDocument.load(r.bytes,{updateMetadata:false}),w=widgets.find(w=>w.pageIndex===2)!,prior=before.context.enumerateIndirectObjects().find(([ref])=>id(ref)===w.widgetId)![1],next=after.context.enumerateIndirectObjects().find(([ref])=>id(ref)===w.widgetId)![1];assert.equal(String(next),String(prior),'skipped shared-field Widget must not regenerate /AP')
 const changed=new Set(widgets.filter(w=>w.pageIndex!==2).map(w=>w.widgetId)),originals=new Map(immutable(before,changed));for(const[ref,value]of immutable(after,changed))if(originals.has(ref))assert.deepEqual(value,originals.get(ref),'untouched '+ref)
})

test('arrangement saves once and output review failure retains actual bytes and failed receipt',async()=>{
 const {b,op}=await setup(true),save=PDFDocument.prototype.save,load=PDFDocument.load;let writes=0
 try{PDFDocument.prototype.save=async function(...args){writes++;return save.apply(this,args)};PDFDocument.load=async(...args)=>{const d=await load.call(PDFDocument,...args);if(sha(args[0]as Uint8Array)!==sha(b))d.getForm=()=>{throw Error('injected arrangement readback')};return d};const r=await arrangeDesignWidgets(b,sha(b),op);assert.equal(writes,1);assert.equal(r.sha256,sha(r.bytes));assert.equal(r.size,r.bytes.length);assert.deepEqual(r.appliedOperationIndices,[]);assert.match(r.skippedOperations[0].reason,/output_review_failed.*injected arrangement readback/);const after=await load.call(PDFDocument,r.bytes,{updateMetadata:false});assert.equal(after.getForm().getTextField('p0f0').getText(),'p0f0')
 }finally{PDFDocument.prototype.save=save;PDFDocument.load=load}
})
test('indirect original AP dictionaries and skipped shared appearance streams remain untouched',async()=>{
 const {b}=await setup(true),d=await PDFDocument.load(b,{updateMetadata:false}),field=d.getForm().getTextField('p0f0'),widgets=field.acroField.getWidgets(),ap=widgets[0].dict.lookup(PDFName.of('AP'),PDFDict),ref=d.context.register(ap);widgets[0].dict.set(PDFName.of('AP'),ref);widgets[1].dict.set(PDFName.of('AP'),ref)
 const source=await d.save({useObjectStreams:false,updateFieldAppearances:false}),census=(await inspectDesignWidgets(source)).widgets,op={kind:'arrangeFormWidgets' as const,sourceSha256:sha(source),targets:census.map(target),alignment:'sameSize' as const},r=await arrangeDesignWidgets(source,sha(source),op);assert.deepEqual(r.skippedOperations,[])
 const before=await PDFDocument.load(source,{updateMetadata:false}),out=await PDFDocument.load(r.bytes,{updateMetadata:false});assert.equal(String(out.context.lookup(ref)),String(before.context.lookup(ref)));assert.equal(String(out.getForm().getTextField('p0f0').acroField.getWidgets()[1].dict),String(before.getForm().getTextField('p0f0').acroField.getWidgets()[1].dict))
 if(process.env.PDF_FORM_MULTIPAGE_EVIDENCE){const directory=process.env.PDF_FORM_MULTIPAGE_EVIDENCE;await mkdir(directory,{recursive:true});await writeFile(directory+'/native-baseline.pdf',source);await writeFile(directory+'/native-arranged.pdf',r.bytes);await writeFile(directory+'/native-operation.json',JSON.stringify(op))}
})
