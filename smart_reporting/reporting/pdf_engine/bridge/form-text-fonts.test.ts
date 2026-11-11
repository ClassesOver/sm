import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,PDFDict,PDFName,PDFRawStream} from 'pdf-lib'
import {createDesignField,bodySnapshot} from './form-design-create'
import {inspectDesignWidgets} from './form-design'
import {editDesignTextProperties} from './form-text-properties'
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
const faces=['Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'] as const
function objectHash(object:unknown){return object instanceof PDFRawStream?hash(Buffer.concat([Buffer.from(object.dict.toString()),Buffer.from(object.contents)])):hash(String(object))}
async function fixture(){let bytes:Uint8Array=await readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url));for(const[name,value,y]of [['party.name','Alice',230],['party.code','C001',180]]as const)bytes=(await createDesignField(bytes,hash(bytes),{kind:'createFormField',sourceSha256:hash(bytes),pageId:'sha256:'+hash(bytes)+':page:0',fieldName:name,fieldKind:'text',required:false,rect:[30,y,180,y+30],value})).bytes;return bytes}
const source=await fixture()
async function operation(){const target=(await inspectDesignWidgets(source)).widgets.find(widget=>widget.fieldName==='party.name')!;return {kind:'editFormTextProperties' as const,sourceSha256:hash(source),fieldName:target.fieldName,widgetId:target.widgetId,widgetIdentity:target.widgetIdentity,expectedWidgetSha256:target.expectedWidgetSha256}}
for(const fontName of faces)test('explicit standard face '+fontName+' updates target AP without altering values references or original objects',async()=>{
 const original=await PDFDocument.load(source),target=original.getForm().getTextField('party.name'),widget=target.acroField.getWidgets()[0],widgetRef=original.context.getObjectRef(widget.dict)!,except=new Set([String(target.ref),String(widgetRef)]),preserved=original.context.enumerateIndirectObjects().filter(([ref])=>!except.has(String(ref))).map(([ref,object])=>[ref,objectHash(object)]as const)
 const result=await editDesignTextProperties(source,hash(source),{...await operation(),fontName})
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0]);assert.equal(result.sha256,hash(result.bytes))
 const out=await PDFDocument.load(result.bytes),field=out.getForm().getTextField('party.name'),outWidget=field.acroField.getWidgets()[0],normal=outWidget.dict.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'),PDFRawStream),fonts=normal.dict.lookup(PDFName.of('Resources'),PDFDict).lookup(PDFName.of('Font'),PDFDict)
 assert.equal(field.getText(),'Alice');assert.equal(String(field.ref),String(target.ref));assert.equal(String(out.context.getObjectRef(outWidget.dict)),String(widgetRef));assert.deepEqual(bodySnapshot(out),bodySnapshot(original));for(const[ref,digest]of preserved)assert.equal(objectHash(out.context.lookup(ref)),digest,String(ref))
 assert.equal(fonts.keys().length,1);assert.equal(String(fonts.lookup(fonts.keys()[0],PDFDict).get(PDFName.of('BaseFont'))),'/'+fontName);assert.equal((await inspectDesignWidgets(result.bytes)).widgets.find(w=>w.fieldName==='party.name')?.textProperties?.fontName,fontName)
})
test('font choice is strict and cannot use unsupported symbolic or custom faces',async()=>{
 const op=await operation();for(const fontName of ['',null,'Symbol','ZapfDingbats','CustomFont','Helvetica; x'])await assert.rejects(editDesignTextProperties(source,hash(source),{...op,fontName}as any),/invalid/)
})
