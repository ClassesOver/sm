import { expect, it } from 'vitest'
import { validatePdfStaticText } from './pdf-static-text'
import { pdfPageState, type PdfPageIdentity } from './pdf-operations'
const sha = 'a'.repeat(64), pageId = `sha256:${sha}:page:0`
const pages: PdfPageIdentity[] = [{ pageId, index: 0, rotation: 0, cropBox: { x: 10, y: 20, width: 300, height: 400 }, mediaBox: { x: 0, y: 0, width: 400, height: 500 } }]
const operation = { kind: 'insertText', sourceSha256: sha, pageId, origin: [100, 200], text: '报告 123', fontSize: 18, color: [0.2, 0.4, 0.6], align: 'left' }
it('validates an independent source-bound insert without changing page geometry', () => {
  expect(pdfPageState(pages, [operation])).toEqual(pages)
})
it.each([
  { sourceSha256: 'b'.repeat(64) }, { pageId: 'foreign' }, { origin: [9, 200] }, { origin: [100, 421] },
  { origin: [NaN, 200] }, { text: ' ' }, { text: 'bad\u0000text' },
  { text: 'a'.repeat(1001) }, { fontSize: 5 }, { fontSize: 73 }, { color: [0, 0, 2] }, { invisible: true }, { text: 'hidden'+String.fromCodePoint(0x200b)+'format' },
])('rejects invalid or stale inserted text %j', patch => {
  expect(() => pdfPageState(pages, [{ ...operation, ...patch }])).toThrow()
})
it('refuses insertion with another operation or multiple insertions', () => {
  expect(() => pdfPageState(pages, [operation, { kind: 'rotatePage', pageId, delta: 90 }])).toThrow('单独')
  expect(() => pdfPageState(pages, [operation, operation])).toThrow('单独')
})

it('accepts source supported multiline fonts styles and alignments', () => {
 for (const align of ['left', 'center', 'right']) expect(() => validatePdfStaticText(pages, [{...operation, text: 'First\n\nSecond', font: 'times', bold: true, italic: true, lineLeading: 18, align}])).not.toThrow()
})
it.each([{font:'other'},{bold:'true'},{italic:1},{align:'justify'},{lineLeading:0},{lineLeading:Infinity},{text:'a\rb'}])('rejects unsupported text options %j', patch => {
 expect(() => validatePdfStaticText(pages, [{...operation,...patch}])).toThrow()
})
