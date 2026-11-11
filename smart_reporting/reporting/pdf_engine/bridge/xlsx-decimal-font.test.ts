import assert from 'node:assert/strict'
import test from 'node:test'
import {execFileSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'
import {resolveOutputFamily} from '../vendor/pdf2docx/src/rebuild/fontmap'
import {parseCellValue} from '../vendor/pdf2docx/src/rebuild-xlsx/numbers'
import {rebuildXlsx,ptToColumnChars} from '../vendor/pdf2docx/src/rebuild-xlsx/rebuild'
import type {IrPage,TextBlock,TableBlock} from '../vendor/pdf2docx/src/ir'

test('plain and grouped non-exponent decimals retain every authored decimal place',()=>{
 for(const [text,value,numFmt] of [['12345.67',12345.67,'0.00'],['12345.6789',12345.6789,'0.0000'],['-31.10',-31.1,'0.00'],['0.00025',.00025,'0.00000'],['12,345.678',12345.678,'#,##0.000'],['1,234.5',1234.5,'#,##0.0']] as const)assert.deepEqual(parseCellValue(text),{kind:'number',value,numFmt})
 for(const [text,value] of [['12',12],['1.25e3',1250],['1.20e-2',.012]] as const)assert.deepEqual(parseCellValue(text),{kind:'number',value,numFmt:'General'})
 for(const text of ['001.20','2026-11-11','1234567890123456'])assert.deepEqual(parseCellValue(text),{kind:'text',text})
 assert.deepEqual(parseCellValue('12.5%'),{kind:'number',value:.125,numFmt:'0.0%'})
})

test('exact PDFium Chrom Sans PS alias respects installed-first and unavailable fallback',()=>{
 assert.equal(resolveOutputFamily('Chrom Sans PS',family=>family==='Liberation Sans'),'Liberation Sans')
 assert.equal(resolveOutputFamily('Chrom Sans PS',family=>family==='Chrom Sans PS'||family==='Liberation Sans'),'Chrom Sans PS')
 assert.equal(resolveOutputFamily('Chrom Sans PS',()=>false),'Chrom Sans PS')
 assert.equal(resolveOutputFamily('Unknown Sans PS',family=>family==='Liberation Sans'),'Unknown Sans PS')
})

test('a standalone decimal claims source width and padding without global text autofit',async()=>{
 const block:TextBlock={kind:'text',box:{x0:60,y0:100,x1:125,y1:118},align:'left',dir:'ltr',firstLineIndentPt:0,lines:[{baseline:102,box:{x0:60,y0:100,x1:125,y1:118},endsWithHyphen:false,spans:[{text:'12345.67',fontFamily:'Liberation Sans',fontSize:14,bold:true,italic:false,box:{x0:60,y0:100,x1:125,y1:118},dir:'ltr',script:'latin',color:'000000'}]}]}
 const page={index:0,widthPt:600,heightPt:800,blocks:[block],scanned:false,degraded:false} as IrPage
 const result=await rebuildXlsx([page]);assert.ok(result.sheets[0]!.colWidths?.[0]!>=ptToColumnChars(65+5*3/4))
 const plain=await rebuildXlsx([{...page,blocks:[{...block,lines:[{...block.lines[0]!,spans:[{...block.lines[0]!.spans[0]!,text:'ordinary text'}]}]}]}]);assert.equal(plain.sheets[0]!.colWidths,undefined)
})

test('actual stable complex PDF uses native bold italic and fixed decimal formats with typed numbers',async()=>{
 const dir=process.env.PDF_XLSX_DECIMAL_FONT_EVIDENCE_DIR??'/tmp/pdf-xlsx-decimal-font/native',repo=fileURLToPath(new URL('../../../../',import.meta.url));await mkdir(dir,{recursive:true})
 execFileSync(repo+'.venv/bin/python',[fileURLToPath(new URL('../../../report_editor/frontend/smoke/pdf-xlsx-decimal-font-source.py',import.meta.url)),dir+'/source.pdf'])
 const source=await readFile(dir+'/source.pdf'),result=await convertPdfOffice(source,{format:'xlsx',sourceSha256:createHash('sha256').update(source).digest('hex')}),zip=await JSZip.loadAsync(result.bytes),sheet=await zip.file('xl/worksheets/sheet2.xml')!.async('string'),styles=await zip.file('xl/styles.xml')!.async('string')
 await writeFile(dir+'/converted.xlsx',result.bytes);await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))
 assert.doesNotMatch(sheet,/Chrom Sans PS/);assert.match(sheet,/<rPr>[^<]*(?:<(?!\/rPr>)[^>]+>)*?<rFont val="Liberation Sans"/)
 const cell=(address:string)=>new RegExp('<c\\b[^>]*r="'+address+'"[^>]*>[\\s\\S]*?<\\/c>').exec(sheet)![0]
 const xfs=[.../<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/.exec(styles)![1]!.matchAll(/<xf\b[^>]*?(?:\/>|>[\s\S]*?<\/xf>)/g)].map(m=>m[0]),formats=new Map([...styles.matchAll(/<numFmt numFmtId="(\d+)" formatCode="([^"]+)"/g)].map(m=>[m[1]!,m[2]!]))
 for(const [address,value,format]of [['A3','12345.67','0.00'],['A4','12345.6789','0.0000'],['A5','-31.1','0.00'],['A6','12345.678','#,##0.000']] as const){const xml=cell(address);assert.match(xml,new RegExp('<v>'+value.replace('.','\\.')+'<\\/v>'));assert.doesNotMatch(xml,/<is>|<r>/);const xf=xfs[Number(/\bs="(\d+)"/.exec(xml)![1])]!;assert.equal(formats.get(/numFmtId="(\d+)"/.exec(xf)![1]),format)}
 assert.match(sheet,/<cols><col min="1" max="1" width="[\d.]+" customWidth="1"\/><\/cols>/);assert.equal(result.validation.ok,false)
})

test('numeric width uses real output advances, retains wider table claims and leaves integer/exponent widths alone',async()=>{
 const block:TextBlock={kind:'text',box:{x0:60,y0:100,x1:61,y1:118},align:'left',dir:'ltr',firstLineIndentPt:0,lines:[{baseline:102,box:{x0:60,y0:100,x1:61,y1:118},endsWithHyphen:false,spans:[{text:'12345.67',fontFamily:'Liberation Sans',fontSize:14,bold:true,italic:false,box:{x0:60,y0:100,x1:61,y1:118},dir:'ltr',script:'latin',color:'000000'}]}]}
 const page={index:0,widthPt:600,heightPt:800,blocks:[block],scanned:false,degraded:false} as IrPage
 const measured=await rebuildXlsx([page]);assert.ok(measured.sheets[0]!.colWidths?.[0]!>ptToColumnChars(50))
 const table:TableBlock={kind:'table',box:{x0:60,y0:50,x1:260,y1:80},colWidthsPt:[200],rows:[[{gridSpan:1,box:{x0:60,y0:50,x1:260,y1:80},blocks:[{...block,lines:[{...block.lines[0]!,spans:[{...block.lines[0]!.spans[0]!,text:'heading'}]}]}]}]]}
 const wider=await rebuildXlsx([{...page,blocks:[block,table]}]);assert.equal(wider.sheets[0]!.colWidths?.[0],ptToColumnChars(200))
 for(const text of ['12345','1.25e3']){const plain=await rebuildXlsx([{...page,blocks:[{...block,lines:[{...block.lines[0]!,spans:[{...block.lines[0]!.spans[0]!,text}]}]}]}]);assert.equal(plain.sheets[0]!.colWidths,undefined)}
})
