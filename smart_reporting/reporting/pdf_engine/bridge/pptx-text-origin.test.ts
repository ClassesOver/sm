import assert from 'node:assert/strict'
import test from 'node:test'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {analyzeChars} from '../vendor/pdf2docx/src/analyze/chars'
import {rebuildPptx} from '../vendor/pdf2docx/src/rebuild-pptx/rebuild'
import type {IrPage,Line,PdfChar,TextBlock} from '../vendor/pdf2docx/src/ir'
import {convertPdfOffice} from './convert-office'

const char=(text:string,x:number,inkX:number,patch:Partial<PdfChar>={}):PdfChar=>({code:text.codePointAt(0)!,text,box:{x0:inkX,y0:148,x1:inkX+8,y1:158},looseBox:{x0:x,y0:148,x1:x+10,y1:160},originX:x,originY:150,originMeasured:true,angle:0,fontSize:10,fontWeight:400,fontFamily:'DejaVu Sans',italic:false,color:'000000',isGenerated:false,isHyphen:false,script:'latin',...patch})
const shapeXml=(xml:string,label:string)=>[...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)].map(match=>match[0]).find(item=>item.includes('<a:t>'+label+'</a:t>'))!
const offset=(xml:string)=>Object.fromEntries([...xml.matchAll(/<a:off x="(-?\d+)" y="(-?\d+)"/g)].map(match=>['x',Number(match[1])]).slice(0,1))
const block=(label:string,originX:number|undefined,patch:Partial<TextBlock>={}):TextBlock=>({kind:'text',box:{x0:22,y0:120,x1:140,y1:158},align:'left',dir:'ltr',firstLineIndentPt:0,lines:[150,134].map((baseline,i)=>({baseline,...(originX===undefined?{}:{originX}),box:{x0:22,y0:baseline-2,x1:140,y1:baseline+8},endsWithHyphen:false,spans:[{text:label+(i?' second':''),box:{x0:22,y0:baseline-2,x1:140,y1:baseline+8},fontSize:10,fontFamily:'DejaVu Sans',bold:false,italic:false,dir:'ltr',script:'latin',color:'000000'}]} as Line)),...patch})

test('horizontal LTR analysis carries the authored glyph origin instead of its positive or negative ink bearing',()=>{
 for(const bearing of [1,-2]){
  const lines=analyzeChars([char('A',20,20+bearing),char('B',30,30+bearing)])
  assert.equal(lines.length,1);assert.equal(lines[0]!.originX,20);assert.equal(lines[0]!.box.x0,20+bearing)
 }
})
test('rotated, RTL and unavailable source origins do not claim a horizontal baseline anchor',()=>{
 for(const chars of [[char('A',20,21,{angle:Math.PI/2})],[char('א',20,21,{script:'hebrew'})],[char('A',NaN,21)],[char('A',20,21,{originMeasured:false})],[char('A',20,21,{originMeasured:undefined})],[char('□',10,10,{isGenerated:true,originMeasured:false}),char('A',20,21)]]){
  const lines=analyzeChars(chars);assert.equal(lines.length,1);assert.equal(lines[0]!.originX,undefined)
 }
})
test('only common left-LTR line origins shift PPTX boxes and the existing page mapper still scales them',async()=>{
 const consistent=block('common',20),inconsistent=block('indented',20);inconsistent.lines[1]!.originX=30
 const pages=[300,600].map(widthPt=>({index:0,widthPt,heightPt:widthPt,blocks:[consistent,inconsistent,block('missing',undefined),block('centered',20,{align:'center'}),block('rtl',20,{dir:'rtl'})],scanned:false,degraded:false} as IrPage))
 const zip=await JSZip.loadAsync(await rebuildPptx(pages))
 for(const [index,scale]of [1,.5].entries()){
  const xml=await zip.file('ppt/slides/slide'+(index+1)+'.xml')!.async('string')
  assert.equal(offset(shapeXml(xml,'common')).x,20*scale*12700)
  for(const label of ['indented','missing','rtl'])assert.equal(offset(shapeXml(xml,label)).x,22*scale*12700)
  // Center padding is the existing 4% width allowance; origin metadata must not change that anchor.
  assert.equal(offset(shapeXml(xml,'centered')).x,Math.round(22*scale*12700)-Math.round(Math.round(Math.max(4,118*scale*.04)*12700)/2))
  assert.match(shapeXml(xml,'common'),/<a:noAutofit\/>/)
  assert.match(shapeXml(xml,'common'),/<a:spcPts val="(?:1600|800)"/)
 }
})
test('actual complex PDF anchors both editable columns to source baseline X without compensating font sizes or Y',async()=>{
 const source=await readFile(new URL('./fixtures/complex-layout.pdf',import.meta.url)),sourceSha256=createHash('sha256').update(source).digest('hex')
 const result=await convertPdfOffice(source,{format:'pptx',sourceSha256}),zip=await JSZip.loadAsync(result.bytes),xml=await zip.file('ppt/slides/slide1.xml')!.async('string')
 for(const[label,x]of [['Left column line 1: business metrics 12345',406400],['Right column line 1: business metrics 12345',4025900]] as const){const item=shapeXml(xml,label);assert.ok(item,label);assert.equal(offset(item).x,x);assert.match(item,/<a:off x="\d+" y="1046480"/);assert.match(item,/<a:rPr sz="1000"/);assert.match(item,/<a:spcPts val="1600"/)}
 assert.equal(result.validation.ok,false)
 if(process.env.PDF_PPTX_TEXT_ORIGIN_EVIDENCE_DIR){const dir=process.env.PDF_PPTX_TEXT_ORIGIN_EVIDENCE_DIR;await mkdir(dir,{recursive:true});await writeFile(dir+'/fixed.pptx',result.bytes);await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))}
})
