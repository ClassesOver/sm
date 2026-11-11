import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { init } from '@embedpdf/pdfium'
import { PDFDocument, StandardFonts, rgb } from 'pdf-lib'
import JSZip from 'jszip'
import { pdfiumWasmPath } from '../src/main/wasm-path'
import { extractIrDocument } from '../vendor/pdf2docx/src/pipeline'
import { rebuildDocx } from '../vendor/pdf2docx/src/rebuild/index'
import type { IrPage, Span, TableBlock, TextBlock } from '../vendor/pdf2docx/src/ir'

const span = (text: string, highlight?: string): Span => ({ text, box: { x0: 40, y0: 218, x1: 160, y1: 230 }, fontSize: 12, fontFamily: 'Liberation Sans', bold: false, italic: false, color: '123456', dir: 'ltr', script: 'latin', ...(highlight === undefined ? {} : { highlight }) })
const block = (spans: Span[]): TextBlock => ({ kind: 'text', box: { x0: 40, y0: 218, x1: 160, y1: 230 }, align: 'left', dir: 'ltr', firstLineIndentPt: 0, lines: [{ spans, baseline: 220, box: { x0: 40, y0: 218, x1: 160, y1: 230 }, endsWithHyphen: false }] })
const page = (blocks: IrPage['blocks'], canvas = false): IrPage => ({ index: 0, widthPt: 400, heightPt: 300, rotation: 0, hasStructTree: false, blocks, scanned: false, degraded: false, canvas })
const runs = (xml: string) => [...xml.matchAll(/<w:r>[\s\S]*?<\/w:r>/g)].map(([raw]) => ({ raw, text: [...raw.matchAll(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g)].map(match => match[1]).join('') }))
async function documentXml(pages: IrPage[]) {
  const zip = await JSZip.loadAsync(await rebuildDocx(pages))
  return zip.file('word/document.xml')!.async('string')
}

test('actual PDF exact pale fills survive extraction and remain distinct DOCX character shading', async () => {
  const doc = await PDFDocument.create(), p = doc.addPage([400, 300]), font = await doc.embedFont(StandardFonts.Helvetica)
  doc.setCreationDate(new Date('2026-11-11T00:00:00Z')); doc.setModificationDate(new Date('2026-11-11T00:00:00Z'))
  for (const [i, [text, color]] of [['Peach text', 'FFF2CC'], ['Green text', 'E2F0D9'], ['Yellow text', 'FFFF00']].entries()) {
    const x = 40 + i * 110
    p.drawRectangle({ x: x - 1, y: 217, width: 89, height: 16, color: rgb(parseInt(color!.slice(0, 2), 16) / 255, parseInt(color!.slice(2, 4), 16) / 255, parseInt(color!.slice(4, 6), 16) / 255) })
    p.drawText(text!, { x, y: 220, size: 12, font })
  }
  const raw = readFileSync(pdfiumWasmPath()), wrapped = await init({ wasmBinary: raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) })
  const pdfium = ((wrapped as { pdfium?: unknown }).pdfium ?? wrapped) as Parameters<typeof extractIrDocument>[1]['pdfium'] & { _PDFiumExt_Init(): void }
  pdfium._PDFiumExt_Init()
  const extracted = extractIrDocument(await doc.save(), { pdfium })
  const source = extracted.irPages.flatMap(p => p.blocks.flatMap(b => b.kind === 'text' ? b.lines.flatMap(l => l.spans.map(s => ({ text: s.text.trim(), highlight: s.highlight }))) : []))
  assert.deepEqual(source, [{ text: 'Peach text', highlight: 'FFF2CC' }, { text: 'Green text', highlight: 'E2F0D9' }, { text: 'Yellow text', highlight: 'FFFF00' }])
  const output = runs(await documentXml(extracted.irPages))
  for (const [label, fill] of [['Peach text', 'FFF2CC'], ['Green text', 'E2F0D9']]) {
    const run = output.find(r => r.text.trim() === label)
    assert.ok(run, label); assert.match(run.raw, new RegExp(`<w:shd[^>]*w:fill="${fill}"`))
    assert.doesNotMatch(run.raw, /<w:highlight/)
  }
  assert.match(output.find(r => r.text === 'Yellow text')!.raw, /<w:highlight w:val="yellow"/)
})

test('exact existing named palette remains compatible while white, missing and invalid fills stay unshaded', async () => {
  const palette = [['000000', 'black'], ['0000FF', 'blue'], ['00FFFF', 'cyan'], ['00FF00', 'green'], ['FF00FF', 'magenta'], ['FF0000', 'red'], ['FFFF00', 'yellow'], ['00008B', 'darkBlue'], ['008B8B', 'darkCyan'], ['006400', 'darkGreen'], ['8B008B', 'darkMagenta'], ['8B0000', 'darkRed'], ['808000', 'darkYellow'], ['808080', 'darkGray'], ['C0C0C0', 'lightGray']]
  const blocks = palette.map(([fill, name]) => block([span(name!, fill)]))
  for (const [i, fill] of [undefined, 'FFFFFF', 'ffffff', '#FFF2CC', 'GGGGGG', '12345', 'FFF2CC00'].entries()) blocks.push(block([span(`plain${i}`, fill)]))
  const output = runs(await documentXml([page(blocks)]))
  for (const [, name] of palette) {
    const run = output.find(r => r.text === name)!
    assert.match(run.raw, new RegExp(`<w:highlight w:val="${name}"`)); assert.doesNotMatch(run.raw, /<w:shd/)
  }
  for (const run of output.filter(r => r.text.startsWith('plain'))) assert.doesNotMatch(run.raw, /<w:(?:highlight|shd)/)
})

test('custom RGB shading participates in run merging without extending across plain or other colored text', async () => {
  const output = runs(await documentXml([page([block([span('A', 'fff2cc'), span('B', 'E2F0D9'), span('plain'), span('C', 'FCE4D6')])])]))
  assert.deepEqual(output.map(r => r.text), ['A', 'B', 'plain', 'C'])
  for (const [label, fill] of [['A', 'FFF2CC'], ['B', 'E2F0D9'], ['C', 'FCE4D6']]) assert.match(output.find(r => r.text === label)!.raw, new RegExp(`<w:shd[^>]*w:fill="${fill}"`))
  assert.doesNotMatch(output.find(r => r.text === 'plain')!.raw, /<w:(?:highlight|shd)/)
})

test('table-cell and canvas-frame text keep exact run shading separate from cell fill', async () => {
  const table: TableBlock = { kind: 'table', box: { x0: 40, y0: 200, x1: 300, y1: 250 }, colWidthsPt: [260], rows: [[{ box: { x0: 40, y0: 200, x1: 300, y1: 250 }, gridSpan: 1, fill: 'AABBCC', blocks: [block([span('cell', 'FFF2CC')])] }]] }
  const tableXml = await documentXml([page([table])])
  assert.match(tableXml, /<w:tcPr>[\s\S]*?<w:shd[^>]*w:fill="AABBCC"/)
  assert.match(runs(tableXml).find(r => r.text === 'cell')!.raw, /<w:shd[^>]*w:fill="FFF2CC"/)
  const frameXml = await documentXml([page([block([span('frame', 'E2F0D9')])], true)])
  assert.match(frameXml, /<w:framePr/)
  assert.match(runs(frameXml).find(r => r.text === 'frame')!.raw, /<w:shd[^>]*w:fill="E2F0D9"/)
})

test('adding exact shading preserves source font, decorations, text and paragraph geometry', async () => {
  const source = { ...span('same'), bold: true, italic: true, underline: true, strike: true, charSpacingPt: 0.2 }
  const [plain, shaded] = await Promise.all([documentXml([page([block([source])])]), documentXml([page([block([{ ...source, highlight: 'FFF2CC' }])])])])
  assert.match(shaded, /<w:shd[^>]*w:fill="FFF2CC"/)
  assert.equal(shaded.replace(/<w:shd\b[^>]*\/>/g, ''), plain)
})
