import assert from 'node:assert/strict'
import test from 'node:test'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {PDFDocument,StandardFonts,rgb} from 'pdf-lib'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'
import {StylePool} from '../vendor/pdf2docx/src/rebuild-xlsx/workbook'
import {extractIrDocument} from '../vendor/pdf2docx/src/pipeline'
import type {PdfiumModule} from '../vendor/pdf2docx/src/extract/pdfium'
import {loadPdfium} from '../src/main/text-edit'

const labels=['Underlined amount','Struck adjustment','Regular label','Both decorations']
async function fixture(){
 const document=await PDFDocument.load(await readFile(new URL('./fixtures/complex-layout.pdf',import.meta.url))),page=document.addPage([600,800]),font=await document.embedFont(StandardFonts.Helvetica)
 for(const [index,text]of labels.entries()){
  const y=650-index*50
  page.drawText(text,{x:60,y,size:14,font})
  for(const delta of index===0?[-1.5]:index===1?[4.2]:index===3?[-1.5,4.2]:[])page.drawLine({start:{x:60,y:y+delta},end:{x:60+font.widthOfTextAtSize(text,14),y:y+delta},thickness:.7,color:rgb(0,0,0)})
 }
 return document.save()
}
function fontXml(styles:string,id:number){return [...styles.matchAll(/<font>([\s\S]*?)<\/font>/g)][id]![1]!}
function cellFonts(sheet:string,styles:string){
 const xfs=[.../<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/.exec(styles)![1]!.matchAll(/<xf\b[^>]*fontId="(\d+)"/g)].map(m=>Number(m[1]))
 return new Map([...sheet.matchAll(/<c\b[^>]*s="(\d+)"[^>]*>([\s\S]*?)<\/c>/g)].map(m=>[[...m[2]!.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map(t=>t[1]).join(''),fontXml(styles,xfs[Number(m[1])]!)]))
}
test('XLSX font pool serializes and distinguishes native underline strike both and regular',()=>{
 const styles=new StylePool(),ids=[styles.cellXf({font:{underline:true}}),styles.cellXf({font:{strike:true}}),styles.cellXf({font:{underline:true,strike:true}}),styles.cellXf({font:{}})]
 assert.equal(new Set(ids).size,4)
 const xml=styles.stylesXml()
 assert.match(fontXml(xml,1),/<u\/>/);assert.doesNotMatch(fontXml(xml,1),/<strike/)
 assert.match(fontXml(xml,2),/<strike\/>/);assert.doesNotMatch(fontXml(xml,2),/<u[\s/>]/)
 assert.match(fontXml(xml,3),/<u\/>/);assert.match(fontXml(xml,3),/<strike\/>/)
 assert.doesNotMatch(fontXml(xml,0),/<(?:u|strike)[\s/>]/)
})
test('actual complex PDF retains measured text decorations as editable XLSX fonts with original table images and numbers',async()=>{
 const source=await fixture(),sourceSha256=createHash('sha256').update(source).digest('hex'),ir=extractIrDocument(source,{pdfium:await loadPdfium() as unknown as PdfiumModule,cellData:true,renderScale:2})
 const blocks=ir.irPages[1]!.blocks.filter(b=>b.kind==='text'),spans=labels.map(label=>blocks.flatMap(b=>b.lines.flatMap(l=>l.spans)).find(s=>s.text===label)!)
 assert.equal(spans[0]!.underline,true);assert.equal(spans[1]!.strike,true);assert.equal(spans[2]!.underline,undefined);assert.equal(spans[2]!.strike,undefined);assert.equal(spans[3]!.underline,true);assert.equal(spans[3]!.strike,true)
 const result=await convertPdfOffice(source,{format:'xlsx',sourceSha256}),zip=await JSZip.loadAsync(result.bytes),styles=await zip.file('xl/styles.xml')!.async('string'),second=await zip.file('xl/worksheets/sheet2.xml')!.async('string'),fonts=cellFonts(second,styles),first=await zip.file('xl/worksheets/sheet1.xml')!.async('string')
 if(process.env.PDF_XLSX_TEXT_DECORATION_EVIDENCE_DIR){const dir=process.env.PDF_XLSX_TEXT_DECORATION_EVIDENCE_DIR;await mkdir(dir,{recursive:true});await writeFile(dir+'/source.pdf',source);await writeFile(dir+'/converted.xlsx',result.bytes);await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))}
 assert.match(fonts.get(labels[0]!)!,/<u\/>/);assert.doesNotMatch(fonts.get(labels[0]!)!,/<strike/)
 assert.match(fonts.get(labels[1]!)!,/<strike\/>/);assert.doesNotMatch(fonts.get(labels[1]!)!,/<u[\s/>]/)
 assert.doesNotMatch(fonts.get(labels[2]!)!,/<(?:u|strike)[\s/>]/)
 assert.match(fonts.get(labels[3]!)!,/<u\/>/);assert.match(fonts.get(labels[3]!)!,/<strike\/>/)
 for(const text of ['Complex quarterly report','Left column line 8','Right column line 8','Region','Revenue','Margin'])assert.ok(first.includes(text),text)
 assert.match(first,/<v>12345\.67<\/v>/);assert.match(first,/<v>9876\.54<\/v>/);assert.match(first,/<v>0\.125<\/v>/)
 assert.ok(zip.file('xl/worksheets/sheet1.xml'));assert.ok(Object.keys(zip.files).some(path=>/^xl\/media\//.test(path)))
 assert.equal(result.pages,2);assert.equal(result.validation.ok,false)
})
