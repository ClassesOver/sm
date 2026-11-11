import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFRawStream,StandardFontEmbedder,decodePDFRawStream} from 'pdf-lib'
import {FontNames} from '@pdf-lib/standard-fonts'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {measureLabelBounds} from '../src/main/measure-label-bounds'
const round=(v:number)=>Math.round(v*100)/100
const font=StandardFontEmbedder.for(FontNames.Helvetica)
const cases=[
 {from:[80,200],to:[240,200],label:'3.00 m'},
 {from:[80,300],to:[82,300],label:'W'.repeat(24)},
 {from:[280,180],to:[80,180],label:'AV To (gj)\\'},
 {from:[100,80],to:[100,280],label:'To AV'},
 {from:[80.003,80.007],to:[82.991,82.003],label:'W'.repeat(64)},
 {from:[160,320],to:[80,80],label:'iii WWW (gj)'},
]
function corners(op:typeof cases[number]){
 const [fx,fy]=op.from,[tx,ty]=op.to,angle=Math.atan2(ty-fy,tx-fx),tilt=Math.abs(angle)>Math.PI/2?angle+Math.PI:angle,a=round(Math.cos(tilt)),b=round(Math.sin(tilt)),c=round(-Math.sin(tilt)),d=round(Math.cos(tilt)),e=round((fx+tx)/2),f=round((fy+ty)/2+6)
 let x=0;const result:number[][]=[]
 for(const char of op.label){const glyph=font.encoding.encodeUnicodeCodePoint(char.codePointAt(0)!),box=font.font.FontBBox;for(const gx of [box[0],box[2]])for(const gy of [box[1],box[3]]){const px=(x+gx)*.009,py=gy*.009;result.push([a*px+c*py+e,b*px+d*py+f])}x+=font.font.getWidthOfGlyph(glyph.name)!}return result
}
test('measure formal Helvetica bounds enclose unkerned Tj at its rounded matrix in standalone and styled batches',async()=>{
 const sourceDoc=await PDFDocument.create();sourceDoc.addPage([900,700]).drawText('Original target',{x:30,y:650,size:14});const source=await sourceDoc.save(),m=await inspectPdf(source,true),pageId=m.pages[0]!.pageId,target=m.pages[0]!.textObjects!.find(t=>t.text==='Original target')!
 for(const mixed of [false,true]){
  const drawings=cases.map(op=>({kind:'addDrawing',pageId,shape:'measure',...op,color:[1,0,0],width:2})),ops=mixed?[...drawings,{kind:'replaceText',pageId,sourceSha256:sha256(source),objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'Changed target',font:'courier',fontSize:12}]:drawings,r=await patchPdfWithReceipt(source,ops,sha256(source));assert.deepEqual(r.skippedOperations,[]);assert.deepEqual(r.appliedOperationIndices,ops.map((_,i)=>i));const doc=await PDFDocument.load(r.bytes),annots=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  const directory=process.env.PDF_MEASURE_LABEL_BOUNDS_TEST_DIRECTORY;if(directory){await mkdir(directory,{recursive:true});await writeFile(join(directory,'source.pdf'),source);await writeFile(join(directory,mixed?'mixed.pdf':'standalone.pdf'),r.bytes);await writeFile(join(directory,'cases.json'),JSON.stringify(cases))}
  for(const [index,op] of cases.entries()){const annotation=annots.lookup(index,PDFDict),rect=annotation.lookup(PDFName.of('Rect'),PDFArray).asArray().map(Number),ap=annotation.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'));assert.ok(ap instanceof PDFRawStream);assert.equal(String(ap.dict.get(PDFName.of('BBox'))),String(annotation.get(PDFName.of('Rect'))));for(const [x,y] of corners(op))assert.ok(x>=rect[0]!&&y>=rect[1]!&&x<=rect[2]!&&y<=rect[3]!,`${mixed?'mixed':'standalone'} case ${index}: ${x},${y} outside ${rect}`);const text=Buffer.from(decodePDFRawStream(ap).decode()).toString('ascii');assert.match(text,/\/F1 9 Tf/);assert.match(text,/ Tm\n\(.*\) Tj ET$/);assert.equal(String(annotation.get(PDFName.of('L'))),doc.context.obj([...op.from,...op.to]).toString())}
 }
})

test('measure literal-byte metrics reject Unicode that the pinned Tj does not encode as WinAnsi',()=>{
 assert.throws(()=>measureLabelBounds([20,20],[40,20],'€'),/literal_encoding_mismatch/);assert.throws(()=>measureLabelBounds([20,20],[40,20],'测'),/cannot encode/);assert.ok(measureLabelBounds([20,20],[40,20],'é').every(Number.isFinite))
})
