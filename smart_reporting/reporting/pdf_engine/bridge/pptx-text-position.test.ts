import assert from 'node:assert/strict'
import test from 'node:test'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {rebuildPptx} from '../vendor/pdf2docx/src/rebuild-pptx/rebuild'
import type {IrPage,TextBlock} from '../vendor/pdf2docx/src/ir'
import {convertPdfOffice} from './convert-office'

const textBlock=(align:'left'|'center'|'right',y:number):TextBlock=>({kind:'text',box:{x0:20,y0:y,x1:120,y1:y+10},align,dir:'ltr',firstLineIndentPt:0,lines:[{baseline:y+2,box:{x0:20,y0:y,x1:120,y1:y+10},endsWithHyphen:false,spans:[{text:'Position '+align,box:{x0:20,y0:y,x1:120,y1:y+10},fontSize:10,fontFamily:'DejaVu Sans',bold:false,italic:false,dir:'ltr',script:'Latin',color:'000000'}]}]})
const shapes=(xml:string)=>[...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)].map(match=>match[0])

test('PDF editable text preserves measured boxes without shape-resizing autofit across alignment and page scales',async()=>{
 const page=(widthPt:number,heightPt:number):IrPage=>({pageIndex:0,widthPt,heightPt,blocks:[textBlock('left',150),textBlock('center',120),textBlock('right',90)],scanned:false,degraded:false} as IrPage)
 const bytes=await rebuildPptx([page(300,300),page(600,600)])
 const zip=await JSZip.loadAsync(bytes)
 for(const slideIndex of [1,2]){
  const xml=await zip.file('ppt/slides/slide'+slideIndex+'.xml')!.async('string'),items=shapes(xml)
  assert.equal(items.length,3)
  for(const item of items){
   assert.match(item,/<a:noAutofit\/>/,'measured PDF geometry must not grow/recenter as a PowerPoint editor textbox')
   assert.doesNotMatch(item,/<a:(?:spAutoFit|normAutofit)\b/)
   assert.match(item,/<a:bodyPr\b[^>]*wrap="none"/)
   assert.match(item,/lIns="0" tIns="0" rIns="0" bIns="0"/)
  }
 }
})

test('real complex PDF retains exact leading, text, table and picture with fixed text-body geometry',async()=>{
 const source=await readFile(new URL('./fixtures/complex-layout.pdf',import.meta.url)),sourceSha256=createHash('sha256').update(source).digest('hex')
 const result=await convertPdfOffice(source,{format:'pptx',sourceSha256}),zip=await JSZip.loadAsync(result.bytes),xml=await zip.file('ppt/slides/slide1.xml')!.async('string')
 for(const label of ['Left column line 1','Right column line 1','Code 001 / fixed width']){
  const item=shapes(xml).find(item=>item.includes(label));assert.ok(item,label)
  assert.match(item,/<a:noAutofit\/>/)
  assert.doesNotMatch(item,/<a:(?:spAutoFit|normAutofit)\b/)
  if(label.includes('column')){assert.match(item,/<a:spcPts val="1600"/);assert.equal((item.match(/<a:br\/>/g)??[]).length,7)}
 }
 assert.equal((xml.match(/<a:tbl>/g)??[]).length,1);assert.equal((xml.match(/<p:pic>/g)??[]).length,1)
 assert.equal(result.validation.ok,false)
 if(process.env.PDF_PPTX_TEXT_POSITION_EVIDENCE_DIR){
  const dir=process.env.PDF_PPTX_TEXT_POSITION_EVIDENCE_DIR;await mkdir(dir,{recursive:true});await writeFile(dir+'/fixed.pptx',result.bytes)
  await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))
 }
})
