import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {convertPdfOffice} from './convert-office'
test('complex embedded-font columns table and image preserve editable structure with manual fidelity warning',async()=>{
 const source=await readFile(new URL('./fixtures/complex-layout.pdf',import.meta.url))
 const result=await convertPdfOffice(source,{format:'pptx',sourceSha256:createHash('sha256').update(source).digest('hex')})
 assert.equal(result.pages,1);assert.equal(result.pageResults[0]?.status,'ok');assert.equal(result.validation.ok,false)
 const zip=await JSZip.loadAsync(result.bytes),slide=await zip.file('ppt/slides/slide1.xml')!.async('string')
 // A source hyperlink boundary can split visible text into adjacent runs.
 // Compare within each paragraph, retaining explicit line breaks and boundaries.
 const paragraphs=[...slide.matchAll(/<a:p(?:\s[^>]*)?>([\s\S]*?)<\/a:p>/g)].map(paragraph=>[...paragraph[1]!.matchAll(/<a:t>([\s\S]*?)<\/a:t>|<a:br\b[^>]*\/>/g)].map(token=>token[1]??'\n').join(''))
 for(const text of ['Complex quarterly report','café €','Left column line 8','Right column line 8','12345.67','9876.54','naïve résumé €'])assert.ok(paragraphs.some(paragraph=>paragraph.includes(text)),text)
 assert.ok(slide.includes('<a:tbl>'));assert.ok(slide.includes('<p:pic>'))
 // Source cells have at least 150pt usable width; trailing whitespace must
 // not become a 130pt inset that squeezes numbers into glyph-ink bounds.
 const columns=[...slide.matchAll(/<a:gridCol w="([0-9]+)"/g)].map(match=>Number(match[1]))
 const rows=[...slide.matchAll(/<a:tr\b[^>]*>([\s\S]*?)<\/a:tr>/g)]
 for(const row of rows){const cells=[...row[1]!.matchAll(/<a:tc\b[^>]*>([\s\S]*?)<\/a:tc>/g)];for(const [index,cell]of cells.entries()){
  const margins=/<a:tcPr[^>]*marL="([0-9]+)"[^>]*marR="([0-9]+)"/.exec(cell[1]!)
  assert.ok(margins);assert.ok(columns[index]!-Number(margins[1])-Number(margins[2])>=150*12700,'cell text must retain layout slack')
 }}
 assert.ok(slide.includes('DejaVu Sans'));assert.ok(Object.keys(zip.files).some(path=>/^ppt\/media\/.*\.png$/.test(path)))
 assert.ok(result.validation.issues.some(issue=>issue.includes('人工核对')))
})
