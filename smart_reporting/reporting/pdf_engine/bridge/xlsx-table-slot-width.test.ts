import assert from 'node:assert/strict'
import test from 'node:test'
import {execFileSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'
import {rebuildXlsx,ptToColumnChars} from '../vendor/pdf2docx/src/rebuild-xlsx/rebuild'
import type {IrPage,TextBlock,TableBlock} from '../vendor/pdf2docx/src/ir'

const text=(value:string,x:number,width=30):TextBlock=>({kind:'text',box:{x0:x,y0:100,x1:x+width,y1:118},align:'left',dir:'ltr',firstLineIndentPt:0,lines:[{baseline:102,box:{x0:x,y0:100,x1:x+width,y1:118},endsWithHyphen:false,spans:[{text:value,fontFamily:'Liberation Sans',fontSize:11,bold:false,italic:false,box:{x0:x,y0:100,x1:x+width,y1:118},dir:'ltr',script:'latin',color:'000000'}]}]})
function table(x:number,widths=[100,100],spanHeader=false):TableBlock{
 const total=widths.reduce((a,b)=>a+b,0),cell=(value:string,start:number,span=1)=>({gridSpan:span,box:{x0:start,y0:20,x1:start+widths.slice(0,span).reduce((a,b)=>a+b,0),y1:60},blocks:[text(value,start)]})
 return {kind:'table',box:{x0:x,y0:20,x1:x+total,y1:60},colWidthsPt:widths,rows:[spanHeader?[cell('Merged header',x,2)]:[cell('Region',x),cell('Value',x+widths[0]!)],[cell('East',x),cell('12345.67',x+widths[0]!)]]} as TableBlock
}
const page=(blocks:IrPage['blocks'],index=0)=>({index,widthPt:600,heightPt:800,blocks,scanned:false,degraded:false} as IrPage)
const widths=(points:number[])=>points.map(ptToColumnChars)

test('table grid columns claim every covered slot interval while preserving horizontal merges and typed cells',async()=>{
 const result=await rebuildXlsx([page([text('interior anchor',60),table(20,[100,100],true)])]),sheet=result.sheets[0]!
 assert.deepEqual(sheet.colWidths,widths([40,60,100]));assert.deepEqual(sheet.merges,['A2:C2','A3:B3'])
 assert.equal(sheet.cells.find(c=>c.row===1&&c.col===0)!.value?.kind,'text');assert.deepEqual(sheet.cells.find(c=>c.row===2&&c.col===2)!.value,{kind:'number',value:12345.67})
})

test('continuation tables allocate using inherited run bounds without duplicate headers or shifted merges',async()=>{
 const result=await rebuildXlsx([page([text('anchor one',70),table(20)],0),page([table(21.6),text('anchor two',70.4)],1)]),sheet=result.sheets[0]!
 assert.equal(result.sheets.length,1);assert.equal(sheet.name,'Pages 1-2');assert.deepEqual(sheet.colWidths,widths([50,50,100]));assert.deepEqual(sheet.merges,['A2:B2','A3:B3','A4:B4'])
 assert.equal(sheet.cells.filter(c=>c.value?.kind==='text'&&c.value.text==='Region').length,1);assert.equal(sheet.cells.filter(c=>c.value?.kind==='number').length,2)
})

test('overlapping tables share source interval claims and retain each distinct merge span',async()=>{
 const sheet=(await rebuildXlsx([page([table(20),table(70)])])).sheets[0]!
 assert.deepEqual(sheet.colWidths,widths([50,50,50,50,50]));assert.deepEqual(sheet.merges,['A1:B1','C1:D1','A2:B2','C2:D2','B4:C4','D4:E4','B5:C5','D5:E5'])
})

test('wider numeric claims, uncovered gaps and collapsed tiny grids retain their existing boundaries',async()=>{
 const sheet=(await rebuildXlsx([page([text('12345.67',70,180),table(20)])])).sheets[0]!
 assert.deepEqual(sheet.colWidths,widths([50,180+5*3/4,100]));assert.deepEqual(sheet.cells.find(c=>c.row===0)!.value,{kind:'number',value:12345.67})
 const gaps=(await rebuildXlsx([page([table(20,[50,50]),text('gap anchor',170),table(220,[50,50])])])).sheets[0]!
 assert.deepEqual(Array.from(gaps.colWidths!),[...widths([50,50]),undefined,undefined,...widths([50,50])])
 const tiny=table(20,[1,1]);const collapsed=(await rebuildXlsx([page([tiny])])).sheets[0]!
 assert.ok(collapsed.colWidths?.every(value=>value===2));assert.ok(collapsed.cells.some(c=>c.value?.kind==='text'&&c.value.text==='Region'))
})

test('same-source complex PDF removes internal default-width slots without altering table cells merges or pictures',async()=>{
 const dir=process.env.PDF_XLSX_TABLE_SLOT_EVIDENCE_DIR??'/tmp/pdf-xlsx-table-slot-width/native',repo=fileURLToPath(new URL('../../../../',import.meta.url));await mkdir(dir,{recursive:true})
 execFileSync(repo+'.venv/bin/python',[fileURLToPath(new URL('../../../report_editor/frontend/smoke/pdf-xlsx-table-slot-width-source.py',import.meta.url)),dir+'/source.pdf'])
 const source=await readFile(dir+'/source.pdf'),result=await convertPdfOffice(source,{format:'xlsx',sourceSha256:createHash('sha256').update(source).digest('hex')}),zip=await JSZip.loadAsync(result.bytes),sheet=await zip.file('xl/worksheets/sheet1.xml')!.async('string')
 await writeFile(dir+'/converted.xlsx',result.bytes);await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))
 const cols=[...sheet.matchAll(/<col min="(\d+)" max="\d+" width="([\d.]+)" customWidth="1"\/>/g)];assert.deepEqual(cols.map(c=>Number(c[1])),[1,2,3,4,5,6]);assert.ok(cols.reduce((sum,c)=>sum+(Number(c[2])*7+5)*3/4,0)<600,'builder convention only; this is not a host physical-point fidelity claim')
 assert.deepEqual([...sheet.matchAll(/<mergeCell ref="([^"]+)"/g)].map(m=>m[1]),['A5:B5','C5:E5','A6:B6','C6:E6','A7:B7','C7:E7']);assert.match(sheet,/<v>12345\.67<\/v>/);assert.match(sheet,/<v>0\.125<\/v>/);assert.match(sheet,/Left column line 8/);assert.match(sheet,/Right column line 8/);assert.ok(Object.keys(zip.files).some(name=>name.startsWith('xl/media/')));assert.equal(result.validation.ok,false)
})
