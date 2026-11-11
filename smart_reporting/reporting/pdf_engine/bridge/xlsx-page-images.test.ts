import assert from 'node:assert/strict'
import test from 'node:test'
import JSZip from 'jszip'
import {embedXlsxPageImages} from './xlsx-page-images'
import {applyStaticImage,type StaticImageAddition} from '../../workbook_engine/packages/xlsx-engine/src/chart-add'
import {buildXlsxPackage,StylePool,type SheetSpec} from '../vendor/pdf2docx/src/rebuild-xlsx/workbook'
import {encodeRgbaPng} from '../vendor/pdf2docx/src/extract/png'
import type {ImageBlock,IrPage,TableBlock} from '../vendor/pdf2docx/src/ir'
const image=():ImageBlock=>({kind:'image',box:{x0:10,y0:10,x1:30,y1:30},data:encodeRgbaPng(new Uint8Array(4*4*4).fill(255),4,4),mime:'image/png',pixelWidth:4,pixelHeight:4})
const page=(index:number,images:ImageBlock[]=[image()]):IrPage=>({index,widthPt:100,heightPt:100,rotation:0,blocks:images,scanned:false,degraded:false,hasStructTree:false})
const sheet=(name='Page 1'):SheetSpec=>({name,cells:[{row:0,col:0,styleId:0,value:{kind:'number',value:12345.67}}]})
async function base(sheets:SheetSpec[]){return buildXlsxPackage(sheets,new StylePool())}
function table():TableBlock{return {kind:'table',box:{x0:0,y0:50,x1:100,y1:90},colWidthsPt:[50,50],rows:[['Region','Value'].map(text=>({gridSpan:1,box:{x0:0,y0:50,x1:50,y1:90},blocks:[{kind:'text',lines:[{spans:[{text,fontSize:10}]}]}]}))]} as unknown as TableBlock}

test('continued tables map both source-page images to their actual grouped worksheet',async()=>{
 const pages=[page(0),page(1)]
 for(const p of pages)p.blocks.unshift(table())
 const sheets=[sheet('Pages 1-2')],calls:StaticImageAddition[]=[]
 const result=await embedXlsxPageImages(await base(sheets),pages,sheets,async(bytes,addition)=>{calls.push(addition);return applyStaticImage(bytes,addition)})
 assert.equal(calls.length,2);assert.ok(calls.every(call=>call.worksheetSheetName==='Pages 1-2'))
 assert.equal(calls[0]!.imageId,'pdf-page-1-image-1');assert.equal(calls[1]!.imageId,'pdf-page-2-image-1')
 assert.ok(calls[1]!.anchor.fromRow>calls[0]!.anchor.toRow)
 assert.ok((await (await JSZip.loadAsync(result.bytes)).file('xl/worksheets/sheet1.xml')!.async('string')).includes('<v>12345.67</v>'))
})

test('image failure retains generated cells and later image writes continue',async()=>{
 const sheets=[sheet()],calls:StaticImageAddition[]=[]
 const result=await embedXlsxPageImages(await base(sheets),[page(0,[image(),image()])],sheets,async(bytes,addition)=>{
  calls.push(addition);if(calls.length===1)throw Error('injected picture write failure')
  return applyStaticImage(bytes,addition)
 })
 const zip=await JSZip.loadAsync(result.bytes)
 assert.equal(calls.length,2);assert.ok(zip.file('xl/media/image1.png'))
 assert.ok((await zip.file('xl/worksheets/sheet1.xml')!.async('string')).includes('<v>12345.67</v>'))
 assert.ok(result.warnings.some(warning=>warning.includes('injected picture write failure')))
})

test('oversized pixels unsupported JPEG crop and off-page images give explicit partial warnings',async()=>{
 const huge={...image(),pixelWidth:20_000_001,pixelHeight:1},jpeg={...image(),mime:'image/jpeg' as const,box:{x0:-10,y0:10,x1:30,y1:30}},outside={...image(),box:{x0:110,y0:10,x1:130,y1:30}}
 const sheets=[sheet()];let calls=0
 const result=await embedXlsxPageImages(await base(sheets),[page(0,[huge,jpeg,outside])],sheets,async()=>{calls++;throw Error('must not write')})
 assert.equal(calls,0)
 for(const message of ['预算','JPEG','边界之外'])assert.ok(result.warnings.some(warning=>warning.includes(message)),message)
})

test('reference region starts below the full merged-cell extent',async()=>{
 const s=sheet();s.merges=['A1:A20'];let captured:StaticImageAddition|undefined
 await embedXlsxPageImages(await base([s]),[page(0)],[s],async(bytes,addition)=>{captured=addition;return applyStaticImage(bytes,addition)})
 assert.ok(captured!.anchor.fromRow>19,'pictures must not overlap merged editable rows')
})

test('document-wide image count budget skips excess images without losing workbook bytes',async()=>{
 const sheets=[sheet()];let calls=0
 const result=await embedXlsxPageImages(await base(sheets),[page(0,Array.from({length:101},()=>image()))],sheets,async(bytes)=>{calls++;return {bytes,mediaPart:'xl/media/test-budget.png'}})
 assert.equal(calls,100)
 assert.ok(result.warnings.some(warning=>warning.includes('image 101')&&warning.includes('预算')))
 assert.ok((await (await JSZip.loadAsync(result.bytes)).file('xl/worksheets/sheet1.xml')!.async('string')).includes('<v>12345.67</v>'))
})
