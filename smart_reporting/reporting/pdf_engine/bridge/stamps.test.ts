import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDict, PDFDocument, PDFName } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'

// 1×1 transparent PNG
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
const watermark = { text: '机密', angle: 35, opacity: 0.18, color: '#d0342c', sizeRatio: 0.11 }
const headerFooter = { headerLeft: '', headerCenter: '', headerRight: '', footerLeft: '', footerCenter: '', footerRight: '', pageNumber: true, startAt: 1, fontSize: 9, color: '#666666' }

async function source() {
  const document = await PDFDocument.create(); document.addPage([400, 500]); document.addPage([300, 300])
  return document.save()
}
const xobjects = (page: { node: PDFDict }) => page.node.lookupMaybe(PDFName.of('Resources'), PDFDict)?.lookupMaybe(PDFName.of('XObject'), PDFDict)?.keys().length ?? 0

test('watermark and header/footer stamps are drawn on every surviving page, including new blank pages', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [first, second] = model.pages.map(page => page.pageId)
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'insertBlankPage', pageId: 'blank:s', width: 200, height: 200 },
    { kind: 'setStamps', watermark, headerFooter, images: [png, png], stamps: [
      { pageId: first, image: 0, rect: [0, 0, 400, 500], opacity: 0.18 }, { pageId: first, image: 1, rect: [0, 10, 400, 30] },
      { pageId: second, image: 0, rect: [0, 0, 300, 300], opacity: 0.18 },
      { pageId: 'blank:s', image: 1, rect: [0, 10, 200, 30] },
    ] },
  ], model.sourceSha256)
  const pages = (await PDFDocument.load(result.bytes)).getPages()
  assert.equal(pages.length, 3)
  assert.deepEqual(pages.map(xobjects), [2, 1, 1])
})

test('stamps must cover every surviving page, stay inside it, use PNG images and appear once', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [first, second] = model.pages.map(page => page.pageId)
  const op = (patch: Record<string, unknown>) => ({ kind: 'setStamps', watermark, headerFooter: null, images: [png], stamps: [{ pageId: first, image: 0, rect: [0, 0, 400, 500] }, { pageId: second, image: 0, rect: [0, 0, 300, 300] }], ...patch })
  const cases: unknown[][] = [
    [op({ stamps: [{ pageId: first, image: 0, rect: [0, 0, 400, 500] }] })],
    [op({ stamps: [{ pageId: first, image: 0, rect: [0, 0, 401, 500] }, { pageId: second, image: 0, rect: [0, 0, 300, 300] }] })],
    [op({ images: [Buffer.from('not a png at all').toString('base64')] })],
    [op({ stamps: [{ pageId: first, image: 3, rect: [0, 0, 400, 500] }, { pageId: second, image: 0, rect: [0, 0, 300, 300] }] })],
    [op({ watermark: null })],
    [op({ watermark: { ...watermark, angle: 120 } })],
    [op({}), op({})],
    [{ kind: 'deletePage', pageId: second }, op({})],
    [op({}), { kind: 'setPageSize', preset: 'A4' }],
  ]
  for (const operations of cases) await assert.rejects(patchPdfWithReceipt(bytes, operations, model.sourceSha256), undefined, JSON.stringify(operations).slice(0, 200))
})
