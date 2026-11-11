import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import JSZip from 'jszip'
import { PDFDocument, PDFName, StandardFonts, rgb } from 'pdf-lib'
import { openPptx } from '../../slides_engine/packages/pptx-engine/src/index'
import { PackageArchive } from '../../slides_engine/packages/pptx-engine/src/zip'
import { convertPdfOffice } from './convert-office'
const sha=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
async function source(){
  const pdf=await PDFDocument.create(),font=await pdf.embedFont(StandardFonts.Helvetica)
  for(const [index,text]of ['First editable report 12345','Second editable report 67890'].entries()){const page=pdf.addPage([400,300]);page.drawText(text,{x:30,y:240,size:18,font});page.drawRectangle({x:30,y:40,width:100,height:60,color:index?rgb(0,0,1):rgb(1,0,0)});page.drawText('Additional business content retained',{x:30,y:180,size:12,font})}
  return pdf.save()
}
test('fixed-source local converter creates editable page slides with source identity and review warnings',async()=>{
  const input=await source(),result=await convertPdfOffice(input,{format:'pptx',sourceSha256:sha(input)})
  assert.equal(result.format,'pptx');assert.equal(result.pages,2);assert.equal(result.sourceSha256,sha(input));assert.equal(result.sha256,sha(result.bytes));assert.equal(result.size,result.bytes.length)
  assert.equal(result.pageResults.length,2);assert.ok(result.pageResults.every(page=>page.status!=='ocr'));assert.equal(result.validation.ok,false);assert.ok(result.validation.issues.length)
  const opened=await openPptx(result.bytes);assert.equal(opened.deck.slides.length,2)
  if(process.env.PDF_CONVERT_EVIDENCE_DIR){await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/source.pdf`,input);await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/converted.pptx`,result.bytes);await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/receipt.json`,JSON.stringify({...result,bytes:undefined},null,2))}
})
test('local conversion rejects stale identity unsupported format unknown options and protected PDF before writing',async()=>{
  const input=await source()
  for(const request of [{format:'pptx',sourceSha256:'f'.repeat(64)},{format:'unsupported',sourceSha256:sha(input)},{format:'pptx',sourceSha256:sha(input),ocr:true}])await assert.rejects(convertPdfOffice(input,request))
  const pdf=await PDFDocument.load(input);pdf.catalog.set(PDFName.of('Perms'),pdf.context.obj({}));const protectedBytes=await pdf.save();await assert.rejects(convertPdfOffice(protectedBytes,{format:'pptx',sourceSha256:sha(protectedBytes)}))
})
for(const format of ['docx','xlsx'] as const){
  test(`fixed-source converter writes editable ${format} and retains scanned page images`,async()=>{
    const input=await source(),result=await convertPdfOffice(input,{format,sourceSha256:sha(input)})
    const zip=await JSZip.loadAsync(result.bytes)
    const xml=await zip.file(format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml')!.async('string')
    assert.ok(xml.includes('First editable report'));assert.equal(result.format,format)
    const pdf=await PDFDocument.create(),image=await pdf.embedPng(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABQAAAAKCAIAAAA7N+mxAAAAFUlEQVR4nGP8z0A+YKJA76jmEaIZAHjzARO1LQhGAAAAAElFTkSuQmCC','base64'))
    pdf.addPage([400,300]).drawImage(image,{x:0,y:0,width:400,height:300})
    const scan=await pdf.save(),scanned=await convertPdfOffice(scan,{format,sourceSha256:sha(scan)})
    const scannedZip=await JSZip.loadAsync(scanned.bytes)
    assert.ok(Object.keys(scannedZip.files).some(path=>path.startsWith(format==='docx'?'word/media/':'xl/media/')&&!scannedZip.files[path]!.dir))
    assert.equal(scanned.scannedDocument,true);assert.ok(scanned.warnings.some(message=>message.includes('OCR')))
    if(process.env.PDF_CONVERT_EVIDENCE_DIR){await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/converted.${format}`,result.bytes);await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/scanned.${format}`,scanned.bytes)}
  })
}
test('scan-only PDF keeps a real slide image and explicit scan outcome while OCR stays disabled',async()=>{
  const pdf=await PDFDocument.create(),image=await pdf.embedPng(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABQAAAAKCAIAAAA7N+mxAAAAFUlEQVR4nGP8z0A+YKJA76jmEaIZAHjzARO1LQhGAAAAAElFTkSuQmCC','base64'))
  pdf.addPage([400,300]).drawImage(image,{x:0,y:0,width:400,height:300})
  const input=await pdf.save(),result=await convertPdfOffice(input,{format:'pptx',sourceSha256:sha(input)})
  assert.equal(result.scannedDocument,true);assert.equal(result.pageResults[0]?.status,'scanned');assert.ok(result.warnings.some(message=>message.includes('OCR')))
  assert.equal((await openPptx(result.bytes)).deck.slides.length,1)
  if(process.env.PDF_CONVERT_EVIDENCE_DIR)await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/scanned.pptx`,result.bytes)
})
test('real output review failure returns the actual generated PPTX bytes with explicit issues',async()=>{
  const input=await source(),original=PackageArchive.open
  PackageArchive.open=async function(bytes){
    const archive=await original.call(this,bytes)
    if(archive.readText('ppt/slides/slide2.xml')?.includes('Second editable report'))throw Error('injected actual PPTX output review failure')
    return archive
  }
  let result:Awaited<ReturnType<typeof convertPdfOffice>>
  try{result=await convertPdfOffice(input,{format:'pptx',sourceSha256:sha(input)})}finally{PackageArchive.open=original}
  assert.equal(result.sha256,sha(result.bytes));assert.equal(result.size,result.bytes.length);assert.equal((await openPptx(result.bytes)).deck.slides.length,2)
  assert.equal(result.validation.ok,false);assert.ok(result.validation.issues.some(issue=>issue.includes('injected actual PPTX output review failure')))
  if(process.env.PDF_CONVERT_EVIDENCE_DIR)await writeFile(`${process.env.PDF_CONVERT_EVIDENCE_DIR}/review-failed.pptx`,result.bytes)
})
test('page and pixel budgets reject before the conversion engine allocates renders',async()=>{
  for(const kind of ['page-count','pixels','user-unit']){
    const pdf=await PDFDocument.create()
    if(kind==='page-count')for(let i=0;i<51;i++)pdf.addPage([100,100])
    else{const page=pdf.addPage(kind==='pixels'?[20000,20000]:[400,300]);if(kind==='user-unit')page.node.set(PDFName.of('UserUnit'),pdf.context.obj(100))}
    const input=await pdf.save();await assert.rejects(convertPdfOffice(input,{format:'pptx',sourceSha256:sha(input)}),/预算|50/)
  }
})
