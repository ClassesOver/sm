import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { init } from '@embedpdf/pdfium'
import { PDFDocument, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import JSZip from 'jszip'
import { XMLParser } from 'fast-xml-parser'
import { pdfiumWasmPath } from '../src/main/wasm-path'
import { extractIrDocument } from '../vendor/pdf2docx/src/pipeline'
import { rebuildPptx } from '../vendor/pdf2docx/src/rebuild-pptx/rebuild'
import { blockRuns, textBlockParagraph } from '../vendor/pdf2docx/src/rebuild-pptx/text'
import type { IrPage, Span, TableBlock, TextBlock } from '../vendor/pdf2docx/src/ir'

const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '', trimValues: false, parseTagValue: false })
const array = <T>(value: T | T[] | undefined): T[] => value === undefined ? [] : Array.isArray(value) ? value : [value]
const span = (text: string, href?: string): Span => ({ text, box: { x0: 40, y0: 218, x1: 250, y1: 230 }, fontSize: 12, fontFamily: 'Liberation Sans', bold: false, italic: false, color: '123456', dir: 'ltr', script: 'latin', ...(href === undefined ? {} : { href }) })
const block = (spans: Span[]): TextBlock => ({ kind: 'text', box: { x0: 40, y0: 218, x1: 250, y1: 230 }, align: 'left', dir: 'ltr', firstLineIndentPt: 0, lines: [{ spans, baseline: 220, originX: 40, box: { x0: 40, y0: 218, x1: 250, y1: 230 }, endsWithHyphen: false }] })
const page = (blocks: IrPage['blocks'], index = 0): IrPage => ({ index, widthPt: 400, heightPt: 300, rotation: 0, hasStructTree: false, blocks, scanned: false, degraded: false })
async function slideParts(pages: IrPage[]) {
  const zip = await JSZip.loadAsync(await rebuildPptx(pages))
  return Promise.all(pages.map(async (_, i) => {
    const xml = await zip.file(`ppt/slides/slide${i + 1}.xml`)!.async('string')
    const relXml = await zip.file(`ppt/slides/_rels/slide${i + 1}.xml.rels`)!.async('string')
    const rels = array(parser.parse(relXml).Relationships.Relationship) as Array<{ Id: string; Type: string; Target: string; TargetMode?: string }>
    const runs = [...xml.matchAll(/<a:r>[\s\S]*?<\/a:r>/g)].map(([raw]) => ({ raw, text: parser.parse(raw)['a:r']['a:t'], rid: /<a:hlinkClick\b[^>]*\br:id="([^"]*)"/.exec(raw)?.[1] }))
    return { xml, rels, runs }
  }))
}

test('actual PDF link annotations survive measured extraction as separate PPTX run relationships', async () => {
  const doc = await PDFDocument.create()
  doc.setCreationDate(new Date('2026-11-11T00:00:00Z')); doc.setModificationDate(new Date('2026-11-11T00:00:00Z'))
  const p = doc.addPage([400, 300]), destination = doc.addPage([400, 300])
  const font = await doc.embedFont(StandardFonts.Helvetica)
  for (const [text, y] of [['Web plain', 220], ['Mail plain', 180], ['Jump plain', 140]] as const) p.drawText(text, { x: 40, y, size: 12, font })
  destination.drawText('Destination', { x: 40, y: 220, size: 12, font })
  const annotations = [
    { Rect: [40, 215, 64, 235], A: { Type: 'Action', S: 'URI', URI: PDFString.of('https://example.com/report?a=1&b=2#part') } },
    { Rect: [40, 175, 62, 195], A: { Type: 'Action', S: 'URI', URI: PDFString.of('mailto:reader@example.com?subject=Report') } },
    { Rect: [40, 135, 70, 155], Dest: [destination.ref, PDFName.of('XYZ'), null, null, null] },
  ].map(spec => doc.context.register(doc.context.obj({ Type: 'Annot', Subtype: 'Link', Border: [0, 0, 0], ...spec })))
  p.node.set(PDFName.of('Annots'), doc.context.obj(annotations))
  const raw = readFileSync(pdfiumWasmPath()), wrapped = await init({ wasmBinary: raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) })
  const pdfium = ((wrapped as { pdfium?: unknown }).pdfium ?? wrapped) as Parameters<typeof extractIrDocument>[1]['pdfium'] & { _PDFiumExt_Init(): void }
  pdfium._PDFiumExt_Init()
  const extracted = extractIrDocument(await doc.save(), { pdfium, absoluteLayout: true })
  const hrefs = extracted.irPages.flatMap(p => p.blocks.flatMap(b => b.kind === 'text' ? b.lines.flatMap(l => l.spans.filter(s => s.href).map(s => s.href)) : []))
  assert.deepEqual(hrefs, ['https://example.com/report?a=1&b=2#part', 'mailto:reader@example.com?subject=Report', '#_pdfpage2'])
  const [first] = await slideParts(extracted.irPages)
  for (const [label, target, mode] of [['Web ', 'https://example.com/report?a=1&b=2#part', 'External'], ['Mail ', 'mailto:reader@example.com?subject=Report', 'External'], ['Jump ', 'slide2.xml', undefined]] as const) {
    const run = first!.runs.find(r => r.text === label)
    assert.ok(run?.rid, label)
    const rel = first!.rels.find(r => r.Id === run.rid)
    assert.equal(rel?.Target, target); assert.equal(rel?.TargetMode, mode)
  }
  assert.equal(first!.runs.filter(r => r.rid).length, 3)
  assert.ok(first!.runs.filter(r => r.text === 'plain').every(r => r.rid === undefined))
})

test('same-style links keep their own target ranges and preserve authored un-underlined color', async () => {
  const b = block([span('A', 'https://example.com/a'), span('plain'), span('B', 'https://example.com/b'), { ...span('underlined', 'mailto:a@example.com'), underline: true }])
  assert.deepEqual(blockRuns(b).map(r => r.text), ['A', 'plain', 'B', 'underlined'])
  const [first] = await slideParts([page([b])])
  assert.equal(first!.runs.length, 4)
  for (const [label, target] of [['A', 'https://example.com/a'], ['B', 'https://example.com/b'], ['underlined', 'mailto:a@example.com']] as const) {
    const run = first!.runs.find(r => r.text === label)!
    assert.equal(first!.rels.find(r => r.Id === run.rid)?.Target, target)
    assert.match(run.raw, /<a:srgbClr val="123456"/)
    assert.match(run.raw, label === 'underlined' ? /\bu="sng"/ : /\bu="none"/)
  }
  assert.equal(first!.runs.find(r => r.text === 'plain')!.rid, undefined)
})

test('table and footnote text use their owning slide links and multi-page GoTo relationships', async () => {
  const table: TableBlock = { kind: 'table', box: { x0: 40, y0: 200, x1: 300, y1: 250 }, colWidthsPt: [260], rows: [[{ box: { x0: 40, y0: 200, x1: 300, y1: 250 }, gridSpan: 1, blocks: [block([span('table', 'https://example.com/table'), span(' third', '#_pdfpage3')])] }]] }
  const pages = [page([table]), page([block([span('back', '#_pdfpage1')])], 1), page([], 2)]
  pages[2]!.footnotes = [{ id: 'f1', blocks: [block([span('note', 'mailto:note@example.com')])] }]
  const parts = await slideParts(pages)
  for (const [index, label, target] of [[0, 'table', 'https://example.com/table'], [0, ' third', 'slide3.xml'], [1, 'back', 'slide1.xml'], [2, 'note', 'mailto:note@example.com']] as const) {
    const part = parts[index]!, run = part.runs.find(r => r.text === label)!
    assert.ok(run?.rid, label); assert.equal(part.rels.find(r => r.Id === run.rid)?.Target, target)
    if (target.startsWith('slide')) assert.match(run.raw, /action="ppaction:\/\/hlinksldjump"/)
  }
})

test('invalid or dangerous targets keep their text without clickable relationships', async () => {
  const bad = ['javascript:alert(1)', 'data:text/html,hello', 'file:///tmp/a', 'slide:0', 'action:nextslide', 'https://example.com/\nfile', 'https://example.com/a b', '#_pdfpage0', '#_pdfpage02', '#_pdfpage-1', '#_pdfpage2x', '#_pdfpage999999999999999999999', '#_pdfpage2']
  const [part] = await slideParts([page(bad.map((href, i) => block([span(`bad${i}`, href)])))])
  assert.equal(part!.runs.length, bad.length)
  assert.ok(part!.runs.every(r => r.rid === undefined))
  assert.equal(part!.rels.filter(r => /\/(hyperlink|slide)$/.test(r.Type)).length, 0)
})

test('adding a link changes no source text geometry, font, spacing or neighboring plain text', async () => {
  const plain = block([span('same')]), linked = block([{ ...span('same', 'http://example.com/'), bold: false }])
  const [[before], [after]] = await Promise.all([slideParts([page([plain])]), slideParts([page([linked])])])
  const clean = (xml: string) => xml.replace(/<a:extLst>[\s\S]*?<\/a:extLst>/g, '').replace(/<a:hlinkClick\b[^>]*\/>/g, '').replace(/ u="none"/g, '')
  assert.ok(after!.runs[0]!.rid)
  assert.equal(clean(after!.xml), clean(before!.xml))
})

test('synthesized list markers and TOC page text do not acquire the neighboring span target', () => {
  const b = block([span('linked title', 'https://example.com/title')])
  for (const patch of [{ list: { kind: 'bullet' as const, level: 0, marker: '•' } }, { tocEntry: { level: 1, pageNumber: '2' } }]) {
    const runs = textBlockParagraph({ ...b, ...patch }).runs
    assert.deepEqual(runs.filter(r => r.hyperlink).map(r => r.text), ['linked title'])
  }
})
