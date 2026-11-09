import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'

const color: [number, number, number] = [0.86, 0.15, 0.15]

async function annotations(bytes: Uint8Array) {
  const page = (await PDFDocument.load(bytes)).getPage(0)
  const annots = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
  return Array.from({ length: annots?.size() ?? 0 }, (_, index) => annots!.lookup(index, PDFDict))
}

test('rectangle, ellipse, arrow and ink drawings land as annotations with colour and geometry', async () => {
  const document = await PDFDocument.create(); document.addPage([400, 500])
  const bytes = await document.save()
  const model = await inspectPdf(bytes)
  const pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'addDrawing', pageId, shape: 'rect', rect: [20, 30, 120, 90], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'ellipse', rect: [150, 30, 250, 130], color, width: 1 },
    { kind: 'addDrawing', pageId, shape: 'arrow', from: [20, 200], to: [200, 260], color, width: 3 },
    { kind: 'addDrawing', pageId, shape: 'ink', paths: [[30, 300, 60, 330, 90, 310]], color, width: 2 },
  ], model.sourceSha256)
  const annots = await annotations(result.bytes)
  const subtypes = annots.map(item => item.get(PDFName.of('Subtype'))?.toString())
  assert.deepEqual(subtypes.sort(), ['/Circle', '/Ink', '/Line', '/Square'])
  for (const annot of annots) {
    const c = annot.lookup(PDFName.of('C'), PDFArray)
    assert.deepEqual(Array.from({ length: c.size() }, (_, index) => Number((c.lookup(index) as PDFNumber).asNumber().toFixed(2))), color)
    assert.ok(annot.get(PDFName.of('AP')), 'each drawing carries an appearance stream')
  }
  const square = annots.find(item => item.get(PDFName.of('Subtype'))?.toString() === '/Square')!
  const rect = square.lookup(PDFName.of('Rect'), PDFArray)
  const [x1, y1, x2, y2] = Array.from({ length: 4 }, (_, index) => (rect.lookup(index) as PDFNumber).asNumber())
  assert.ok(x1 <= 20 && y1 <= 30 && x2 >= 120 && y2 >= 90)
  assert.equal((await inspectPdf(result.bytes)).pageCount, 1)
})

test('drawings outside the page, malformed shapes and blank-page targets are rejected', async () => {
  const document = await PDFDocument.create(); document.addPage([400, 500])
  const bytes = await document.save()
  const model = await inspectPdf(bytes)
  const pageId = model.pages[0]!.pageId
  const cases: unknown[] = [
    { kind: 'addDrawing', pageId, shape: 'rect', rect: [20, 30, 900, 90], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'rect', from: [0, 0], to: [10, 10], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'arrow', from: [20, 20], to: [20.5, 20.5], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'ink', paths: [[30, 300, 60]], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'ink', paths: [[30, 300, 600, 330]], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'rect', rect: [20, 30, 120, 90], color: [2, 0, 0], width: 2 },
    { kind: 'addDrawing', pageId, shape: 'rect', rect: [20, 30, 120, 90], color, width: 0 },
    { kind: 'addDrawing', pageId: 'foreign', shape: 'rect', rect: [20, 30, 120, 90], color, width: 2 },
  ]
  for (const operation of cases) await assert.rejects(patchPdfWithReceipt(bytes, [operation], model.sourceSha256), undefined, JSON.stringify(operation))
  await assert.rejects(patchPdfWithReceipt(bytes, [
    { kind: 'insertBlankPage', pageId: 'blank:a', width: 400, height: 500 },
    { kind: 'addDrawing', pageId: 'blank:a', shape: 'rect', rect: [20, 30, 120, 90], color, width: 2 },
  ], model.sourceSha256))
})

test('polygon and caret drawings land as Polygon and Caret annotations; malformed ones are rejected', async () => {
  const document = await PDFDocument.create(); document.addPage([400, 500])
  const bytes = await document.save()
  const model = await inspectPdf(bytes)
  const pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'addDrawing', pageId, shape: 'polygon', vertices: [[20, 20], [120, 40], [80, 140]], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'caret', point: [200, 300], color, width: 2 },
  ], model.sourceSha256)
  const annots = await annotations(result.bytes)
  assert.deepEqual(annots.map(item => item.get(PDFName.of('Subtype'))?.toString()).sort(), ['/Caret', '/Polygon'])
  const polygon = annots.find(item => item.get(PDFName.of('Subtype'))?.toString() === '/Polygon')!
  assert.equal(polygon.lookup(PDFName.of('Vertices'), PDFArray).size(), 6)
  assert.ok(annots.every(item => item.get(PDFName.of('AP'))))
  for (const operation of [
    { kind: 'addDrawing', pageId, shape: 'polygon', vertices: [[20, 20], [120, 40]], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'polygon', vertices: [[20, 20], [120, 40], [900, 40]], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'caret', point: [900, 300], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'caret', point: [20, 30], rect: [0, 0, 10, 10], color, width: 2 },
  ]) await assert.rejects(patchPdfWithReceipt(bytes, [operation], model.sourceSha256), undefined, JSON.stringify(operation))
})
