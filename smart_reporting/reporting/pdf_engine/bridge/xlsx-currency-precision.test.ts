import assert from 'node:assert/strict'
import test from 'node:test'
import {execFileSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'
import {parseCellValue} from '../vendor/pdf2docx/src/rebuild-xlsx/numbers'
import {rebuildXlsx,ptToColumnChars} from '../vendor/pdf2docx/src/rebuild-xlsx/rebuild'
import {advanceWidths} from '../vendor/font-metrics/src/index'
import type {IrPage,TextBlock} from '../vendor/pdf2docx/src/ir'

test('currency prefixes and suffixes retain authored decimal places without changing percent or plain-number policies',()=>{
 for(const [text,value,numFmt]of [['$12345.678',12345.678,'"$"#,##0.000'],['€31.1',31.1,'"€"#,##0.0'],['-£0.0500',-.05,'"£"#,##0.0000'],['$-45.3',-45.3,'"$"#,##0.0'],['123.456元',123.456,'#,##0.000"元"'],['31.100€',31.1,'"€"#,##0.000'],['￥31.1',31.1,'"¥"#,##0.0'],['$123',123,'"$"#,##0']]as const)assert.deepEqual(parseCellValue(text),{kind:'number',value,numFmt})
 for(const [text,value,numFmt]of [['12.345%',.12345,'0.000%'],['0.0007%',.000007,'0.0000%'],['12',12,'General'],['1.25e3',1250,'General']]as const)assert.deepEqual(parseCellValue(text),{kind:'number',value,numFmt})
})

test('standalone currency and percent widths use rendered punctuation advances and retain plain integer/exponent widths',async()=>{
 const numeric=(text:string):TextBlock=>({kind:'text',box:{x0:60,y0:100,x1:61,y1:118},align:'left',dir:'ltr',firstLineIndentPt:0,lines:[{baseline:102,box:{x0:60,y0:100,x1:61,y1:118},endsWithHyphen:false,spans:[{text,fontFamily:'Liberation Sans',fontSize:14,bold:false,italic:false,box:{x0:60,y0:100,x1:61,y1:118},dir:'ltr',script:'latin',color:'000000'}]}]})
 const page=(text:string)=>({index:0,widthPt:600,heightPt:800,blocks:[numeric(text)],scanned:false,degraded:false} as IrPage)
 for(const [text,display]of [['$12345.678','$12,345.678'],['12.345%','12.345%'],['12345%','12345%']]as const){const converted=await rebuildXlsx([page(text)]),width=advanceWidths('Liberation Sans',display,14)!.reduce((a,b)=>a+b,0)/20;assert.ok(converted.sheets[0]!.colWidths?.[0]!>=ptToColumnChars(width+5*3/4),text)}
 for(const text of ['12345','1.25e3','12,345'])assert.equal((await rebuildXlsx([page(text)])).sheets[0]!.colWidths,undefined)
})

test('actual stable PDF retains typed currency precision and a separate non-table percentage column',async()=>{
 const dir=process.env.PDF_XLSX_CURRENCY_EVIDENCE_DIR??'/tmp/pdf-xlsx-currency-precision/native',repo=fileURLToPath(new URL('../../../../',import.meta.url));await mkdir(dir,{recursive:true})
 execFileSync(repo+'.venv/bin/python',[fileURLToPath(new URL('../../../report_editor/frontend/smoke/pdf-xlsx-currency-precision-source.py',import.meta.url)),dir+'/source.pdf'])
 const source=await readFile(dir+'/source.pdf'),result=await convertPdfOffice(source,{format:'xlsx',sourceSha256:createHash('sha256').update(source).digest('hex')}),zip=await JSZip.loadAsync(result.bytes),sheet=await zip.file('xl/worksheets/sheet2.xml')!.async('string'),styles=await zip.file('xl/styles.xml')!.async('string')
 await writeFile(dir+'/converted.xlsx',result.bytes);await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))
 const cell=(address:string)=>new RegExp('<c\\b[^>]*r="'+address+'"[^>]*>[\\s\\S]*?<\\/c>').exec(sheet)![0],xfs=[.../<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/.exec(styles)![1]!.matchAll(/<xf\b[^>]*?(?:\/>|>[\s\S]*?<\/xf>)/g)].map(m=>m[0]),formats=new Map([...styles.matchAll(/<numFmt numFmtId="(\d+)" formatCode="([^"]+)"/g)].map(m=>[m[1]!,m[2]!.replaceAll('&quot;','"')]))
 for(const [address,value,format]of [['B8','12345.678','"$"#,##0.000'],['B9','31.1','"€"#,##0.0'],['B10','-0.05','"£"#,##0.0000'],['B11','0.12345','0.000%'],['B12','0.000007','0.0000%']]as const){const xml=cell(address);assert.match(xml,new RegExp('<v>'+value.replace('.','\\.')+'<\\/v>'));assert.doesNotMatch(xml,/<is>|<r>/);const xf=xfs[Number(/\bs="(\d+)"/.exec(xml)![1])]!;assert.equal(formats.get(/numFmtId="(\d+)"/.exec(xf)![1]),format)}
 assert.match(sheet,/<col min="2" max="2" width="[\d.]+" customWidth="1"\/>/);assert.equal(result.validation.ok,false)
})
