import assert from 'node:assert/strict'
import test from 'node:test'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,StandardFonts,rgb} from 'pdf-lib'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'
import {rebuildXlsx} from '../vendor/pdf2docx/src/rebuild-xlsx/rebuild'
import {buildXlsxPackage,type SheetSpec,StylePool} from '../vendor/pdf2docx/src/rebuild-xlsx/workbook'
import type {IrPage,Span,TextBlock,TableBlock} from '../vendor/pdf2docx/src/ir'

const sourceLabels=['Plain Bold Italic Under Strike Serif','Dominant decorated words plain']
async function fixture(){
 const document=await PDFDocument.load(await readFile(new URL('./fixtures/complex-layout.pdf',import.meta.url))),page=document.addPage([600,800])
 const regular=await document.embedFont(StandardFonts.Helvetica),bold=await document.embedFont(StandardFonts.HelveticaBold),italic=await document.embedFont(StandardFonts.HelveticaOblique),both=await document.embedFont(StandardFonts.HelveticaBoldOblique),serif=await document.embedFont(StandardFonts.TimesRoman)
 const lines=[{y:650,runs:[['Plain ',regular,false,false],['Bold ',bold,false,false],['Italic ',italic,false,false],['Under ',regular,true,false],['Strike ',regular,false,true],['Serif',serif,false,false]]},{y:600,runs:[['Dominant decorated words ',both,true,true],['plain',regular,false,false]]},{y:550,runs:[['12345',bold,false,false],['.67',regular,false,false]]}]
 for(const {y,runs}of lines){let x=60;for(const [text,font,underline,strike]of runs as [string,typeof regular,boolean,boolean][]){page.drawText(text,{x,y,size:14,font});const width=font.widthOfTextAtSize(text,14);for(const dy of [...underline?[-1.5]:[],...strike?[4.2]:[]])page.drawLine({start:{x,y:y+dy},end:{x:x+width,y:y+dy},thickness:.7,color:rgb(0,0,0)});x+=width}}
 return document.save()
}
const span=(text:string,patch:Partial<Span>={}):Span=>({text,box:{x0:20,y0:520,x1:180,y1:535},fontSize:14,fontFamily:'Liberation Sans',bold:false,italic:false,dir:'ltr',script:'latin',color:'000000',...patch})
const block=(spans:Span[],patch:Partial<TextBlock>={}):TextBlock=>({kind:'text',box:{x0:20,y0:520,x1:180,y1:535},lines:[{spans,baseline:520,box:{x0:20,y0:520,x1:180,y1:535},endsWithHyphen:false}],align:'left',firstLineIndentPt:0,dir:'ltr',...patch})
const page=(blocks:IrPage['blocks']):IrPage=>({index:0,widthPt:600,heightPt:800,blocks,scanned:false,degraded:false} as IrPage)
const cellXml=(xml:string,address:string)=>new RegExp('<c\\b[^>]*r="'+address+'"[^>]*>[\\s\\S]*?<\\/c>').exec(xml)![0]
const runs=(xml:string)=>[...xml.matchAll(/<r>([\s\S]*?)<\/r>/g)].map(match=>({xml:match[1]!,text:/(?<=<t\b[^>]*>)[\s\S]*?(?=<\/t>)/.exec(match[1]!)?.[0]}))
const fontAt=(styles:string,cell:string)=>{const id=Number(/\bs="(\d+)"/.exec(cell)![1]),xf=[.../<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/.exec(styles)![1]!.matchAll(/<xf\b[^>]*?(?:\/>|>[\s\S]*?<\/xf>)/g)][id]![0],font=Number(/fontId="(\d+)"/.exec(xf)![1]);return {xf,font:[...styles.matchAll(/<font>([\s\S]*?)<\/font>/g)][font]![1]!}}

test('actual complex PDF preserves mixed editable XLSX runs and minority regular without converting numbers to strings',async()=>{
 const source=await fixture(),result=await convertPdfOffice(source,{format:'xlsx',sourceSha256:createHash('sha256').update(source).digest('hex')}),zip=await JSZip.loadAsync(result.bytes),sheet=await zip.file('xl/worksheets/sheet2.xml')!.async('string'),styles=await zip.file('xl/styles.xml')!.async('string')
 if(process.env.PDF_XLSX_RICH_TEXT_EVIDENCE_DIR){const dir=process.env.PDF_XLSX_RICH_TEXT_EVIDENCE_DIR;await mkdir(dir,{recursive:true});await writeFile(dir+'/source.pdf',source);await writeFile(dir+'/converted.xlsx',result.bytes);await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))}
 const first=runs(cellXml(sheet,'A1'));assert.equal(first.map(run=>run.text).join(''),sourceLabels[0]);assert.equal(first.length,6)
 assert.match(first[1]!.xml,/<b\/>/);assert.match(first[2]!.xml,/<i\/>/);assert.match(first[3]!.xml,/<u\/>/);assert.match(first[4]!.xml,/<strike\/>/);assert.match(first[5]!.xml,/<rFont val="Liberation Serif"/)
 const second=runs(cellXml(sheet,'A2'));assert.equal(second.map(run=>run.text).join(''),sourceLabels[1]);assert.match(second[0]!.xml,/<b\/>/);assert.match(second[0]!.xml,/<i\/>/);assert.match(second[0]!.xml,/<u\/>/);assert.match(second[0]!.xml,/<strike\/>/);assert.doesNotMatch(second[1]!.xml,/<(?:b|i|u|strike)[\s/>]/)
 assert.doesNotMatch(fontAt(styles,cellXml(sheet,'A2')).font,/<(?:b|i|u|strike)[\s/>]/)
 assert.match(cellXml(sheet,'A3'),/<v>12345\.67<\/v>/);assert.doesNotMatch(cellXml(sheet,'A3'),/<is>|<r>/)
 const firstSheet=await zip.file('xl/worksheets/sheet1.xml')!.async('string');assert.match(firstSheet,/<v>12345\.67<\/v>/);assert.match(firstSheet,/<v>0\.125<\/v>/);assert.ok(firstSheet.includes('Right column line 8'));assert.ok(Object.keys(zip.files).some(name=>name.startsWith('xl/media/')));assert.equal(result.validation.ok,false)
})

test('XLSX emission retains rich candidates across table paragraphs lists and TOC while numbers stay typed',async()=>{
 const mixed=block([span('Decorated ',{bold:true,underline:true}),span('plain')]),list=block([span('List body',{italic:true})],{list:{kind:'ordered',level:0,marker:'1. '}}),toc=block([span('Contents',{fontFamily:'Liberation Serif'})],{tocEntry:{level:0,pageNumber:'7'}})
 const table:TableBlock={kind:'table',box:{x0:20,y0:450,x1:320,y1:550},colWidthsPt:[150,150],borderColor:'334455',rows:[[{gridSpan:2,box:{x0:20,y0:500,x1:320,y1:550},fill:'FFF0AA',vAlign:'center',blocks:[mixed,list,toc]}],[{gridSpan:1,box:{x0:20,y0:450,x1:170,y1:500},blocks:[block([span('12345',{bold:true}),span('.67')])]},{gridSpan:1,box:{x0:170,y0:450,x1:320,y1:500},blocks:[block([span('12.5%')])]}]]}
 const converted=await rebuildXlsx([page([table])]),anchor=converted.sheets[0]!.cells.find(cell=>cell.row===0&&cell.col===0)!
 assert.ok('richText'in anchor);assert.equal((anchor as any).richText.map((run:any)=>run.text).join(''),'Decorated plain\n1. List body\nContents\t7');assert.deepEqual(converted.sheets[0]!.merges,['A1:B1'])
 assert.deepEqual(converted.sheets[0]!.cells.find(cell=>cell.row===1&&cell.col===0)!.value,{kind:'number',value:12345.67});assert.equal('richText'in converted.sheets[0]!.cells.find(cell=>cell.row===1&&cell.col===0)!,false)
})

test('rich patch neutralizes only font switches while keeping table cell formatting and numeric XML',async()=>{
 const {applyXlsxRichText}=await import('./xlsx-rich-text'),styles=new StylePool(),styleId=styles.cellXf({font:{bold:true,italic:true,underline:true,strike:true,name:'Liberation Sans',sizePt:14},fill:'FFF0AA',border:{left:'334455',right:'334455',top:'334455',bottom:'334455'},align:{horizontal:'center',vertical:'center',wrapText:true},numFmt:'0.00'})
 const richText=[{text:'Dominant decorated ',bold:true,italic:true,underline:true,strikethrough:true,family:'Liberation Sans',size:14},{text:'plain',bold:false,italic:false,underline:false,strikethrough:false,family:'Liberation Sans',size:14}],sheets=[{name:'Page 1',cells:[{row:0,col:0,styleId,value:{kind:'text',text:'Dominant decorated plain'},richText},{row:1,col:0,styleId,value:{kind:'number',value:12345.67}}],merges:['A1:B1']}] as SheetSpec[]
 const source=await buildXlsxPackage(sheets,styles),patched=await applyXlsxRichText(source,sheets),before=await JSZip.loadAsync(source),after=await JSZip.loadAsync(patched.bytes),oldSheet=await before.file('xl/worksheets/sheet1.xml')!.async('string'),newSheet=await after.file('xl/worksheets/sheet1.xml')!.async('string'),oldStyles=await before.file('xl/styles.xml')!.async('string'),newStyles=await after.file('xl/styles.xml')!.async('string'),oldFont=fontAt(oldStyles,cellXml(oldSheet,'A1')),newFont=fontAt(newStyles,cellXml(newSheet,'A1'))
 for(const key of ['numFmtId','fillId','borderId'])assert.equal(new RegExp(key+'="(\\d+)"').exec(oldFont.xf)![1],new RegExp(key+'="(\\d+)"').exec(newFont.xf)![1])
 assert.equal(/<alignment[^>]*\/>/.exec(newFont.xf)?.[0],/<alignment[^>]*\/>/.exec(oldFont.xf)?.[0]);assert.doesNotMatch(newFont.font,/<(?:b|i|u|strike)[\s/>]/);assert.match(newFont.font,/<name val="Liberation Sans"/);assert.equal(cellXml(oldSheet,'A2'),cellXml(newSheet,'A2'));assert.match(newSheet,/<mergeCell ref="A1:B1"/);assert.deepEqual(patched.warnings,[])
})

test('normalization changes and forbidden controls keep canonical plain bytes without rich overruns',async()=>{
 const {applyXlsxRichText}=await import('./xlsx-rich-text')
 for(const text of ['x'.repeat(32766)+'😀tail','row\n'.repeat(254)+'end','unsafe\u0001control']){
  const converted=await rebuildXlsx([page([block([span(text.slice(0,1),{bold:true}),span(text.slice(1))])])]);let writes=0
  const result=await applyXlsxRichText(converted.xlsx,converted.sheets,async()=>{writes++;throw Error('must not patch normalized cells')});assert.equal(writes,0);assert.deepEqual(result.bytes,converted.xlsx);assert.ok(result.warnings.some(w=>/plain|纯文本/.test(w)))
  const sheet=await(await JSZip.loadAsync(result.bytes)).file('xl/worksheets/sheet1.xml')!.async('string');assert.doesNotMatch(sheet,/<r>/);assert.doesNotMatch(sheet,/\u0001/)
 }
})

test('exact Excel UTF-16 and line-feed boundaries can retain native mixed runs',async()=>{
 const {applyXlsxRichText}=await import('./xlsx-rich-text')
 for(const text of ['A'+'x'.repeat(32764)+'😀','row\n'.repeat(253)+'end']){
  const converted=await rebuildXlsx([page([block([span(text.slice(0,1),{bold:true}),span(text.slice(1))])])]),result=await applyXlsxRichText(converted.xlsx,converted.sheets),sheet=await(await JSZip.loadAsync(result.bytes)).file('xl/worksheets/sheet1.xml')!.async('string'),actual=runs(cellXml(sheet,'A1')).map(run=>run.text).join('')
  assert.equal(actual,text);assert.ok(actual.length<=32767);assert.ok([...actual.matchAll(/\n/g)].length<=253);assert.deepEqual(result.warnings,[])
 }
})

test('rich writer failure retains original generated plain XLSX identity with a specific warning',async()=>{
 const {applyXlsxRichText}=await import('./xlsx-rich-text'),converted=await rebuildXlsx([page([block([span('bold ',{bold:true}),span('plain')])])]);let calls=0
 const result=await applyXlsxRichText(converted.xlsx,converted.sheets,async()=>{calls++;throw Error('injected rich writer failure')});assert.equal(calls,1);assert.deepEqual(result.bytes,converted.xlsx);assert.ok(result.warnings.some(w=>w.includes('injected rich writer failure')))
 assert.doesNotMatch(await(await JSZip.loadAsync(result.bytes)).file('xl/worksheets/sheet1.xml')!.async('string'),/<r>/)
})
