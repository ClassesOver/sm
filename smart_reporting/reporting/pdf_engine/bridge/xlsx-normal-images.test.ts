import assert from 'node:assert/strict'
import test from 'node:test'
import {readFile,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'

test('normal PDF pages retain editable cells and actual floating images in source-bound reference areas',async()=>{
 const source=await readFile(new URL('./fixtures/xlsx-normal-images.pdf',import.meta.url))
 const result=await convertPdfOffice(source,{format:'xlsx',sourceSha256:createHash('sha256').update(source).digest('hex')})
 const zip=await JSZip.loadAsync(result.bytes)
 const media=Object.keys(zip.files).filter(path=>/^xl\/media\/image\d+\.(png|jpeg)$/.test(path))
 assert.equal(result.pageResults.length,3)
 assert.ok(result.pageResults.every(page=>page.status==='ok'))
 assert.equal(media.length,9,'all three actual image objects on all three normal pages must survive')
 const sheets=await Promise.all(Object.keys(zip.files).filter(path=>/^xl\/worksheets\/sheet\d+\.xml$/.test(path)).map(path=>zip.file(path)!.async('string')))
 assert.ok(sheets.join('').includes('Editable report page'))
 assert.ok(sheets.join('').includes('12345.67'))
 assert.ok(sheets.join('').includes('图片位置参考区'))
 const drawing=await zip.file('xl/drawings/drawing3.xml')!.async('string')
 const rotated=[...drawing.matchAll(/<xdr:twoCellAnchor\b[^>]*>([\s\S]*?)<\/xdr:twoCellAnchor>/g)].find(match=>match[1]!.includes('pdf-page-3-image-1'))![1]!
 assert.ok(rotated.includes('<xdr:row>11</xdr:row><xdr:rowOff>127000</xdr:rowOff>'),'page Rotate90 must use visible display-space image coordinates, not cell-recovered coordinates')
 assert.equal(result.validation.ok,false)
 assert.ok(result.warnings.some(warning=>warning.includes('不代表原图文相对排版')))
 if(process.env.PDF_XLSX_IMAGES_EVIDENCE_DIR){
  const dir=process.env.PDF_XLSX_IMAGES_EVIDENCE_DIR
  await writeFile(dir+'/converted.xlsx',result.bytes)
  await writeFile(dir+'/receipt.json',JSON.stringify({...result,bytes:undefined},null,2))
 }
})
