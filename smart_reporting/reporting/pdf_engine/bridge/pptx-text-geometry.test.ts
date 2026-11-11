import assert from 'node:assert/strict'
import test from 'node:test'
import {readFile,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {textBlockParagraph} from '../vendor/pdf2docx/src/rebuild-pptx/text'
import type {TextBlock} from '../vendor/pdf2docx/src/ir'
import {convertPdfOffice} from './convert-office'
const block=(height:number,baselines:number[]):TextBlock=>({kind:'text',box:{x0:0,y0:0,x1:200,y1:height},align:'left',dir:'ltr',lines:baselines.map((baseline,index)=>({baseline,box:{x0:0,y0:baseline-2,x1:200,y1:baseline+8},spans:[{text:'Line '+(index+1),fontSize:10,fontFamily:'DejaVu Sans',dir:'ltr',script:'Latin',color:'000000'}]}))} as TextBlock)
test('multi-line PPTX pitch uses source baseline distances rather than glyph ink height',()=>{
 const baselines=Array.from({length:8},(_,i)=>120-i*16)
 for(const height of [119.73,121.67])assert.equal(textBlockParagraph(block(height,baselines)).lineExact,16)
})
test('source baseline pitch scales with the existing page mapper',()=>{
 assert.equal(textBlockParagraph(block(37,[90,74,58]),0.5).lineExact,8)
})
test('single lines and unavailable baselines retain the original height fallback',()=>{
 assert.equal(textBlockParagraph(block(22,[90])).lineExact,22)
 assert.equal(textBlockParagraph(block(30,[NaN,NaN,NaN])).lineExact,10)
})
test('actual complex PDF emits 16pt leading for both editable eight-line columns',async()=>{
 const source=await readFile(new URL('./fixtures/complex-layout.pdf',import.meta.url))
 const result=await convertPdfOffice(source,{format:'pptx',sourceSha256:createHash('sha256').update(source).digest('hex')})
 const zip=await JSZip.loadAsync(result.bytes),xml=await zip.file('ppt/slides/slide1.xml')!.async('string')
 for(const label of ['Left column line 1','Right column line 1']){
  const start=xml.lastIndexOf('<p:sp>',xml.indexOf(label)),end=xml.indexOf('</p:sp>',start)
  assert.match(xml.slice(start,end),/spcPts\b[^>]*val=.1600./)
 }
 assert.equal(result.validation.ok,false)
 if(process.env.PDF_PPTX_TEXT_GEOMETRY_EVIDENCE_DIR){
  const dir=process.env.PDF_PPTX_TEXT_GEOMETRY_EVIDENCE_DIR
  await writeFile(dir+'/fixed.pptx',result.bytes)
  await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))
 }
})
