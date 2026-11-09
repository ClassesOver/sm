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

test('links write Link annotations to a URL or a source page and reject unsafe or dangling targets', async () => {
  const document = await PDFDocument.create(); document.addPage([400, 500]); document.addPage([400, 500])
  const bytes = await document.save()
  const model = await inspectPdf(bytes)
  const [first, second] = model.pages.map(page => page.pageId)
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 20, 120, 50], url: 'https://example.com/report', color, width: 2 },
    { kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 60, 120, 90], destPage: 2, color, width: 2 },
  ], model.sourceSha256)
  const output = await PDFDocument.load(result.bytes)
  const annots = (await annotations(result.bytes)).filter(item => item.get(PDFName.of('Subtype'))?.toString() === '/Link')
  assert.equal(annots.length, 2)
  const uriAction = annots.map(item => item.lookupMaybe(PDFName.of('A'), PDFDict)).find(Boolean)!
  assert.equal(uriAction.lookup(PDFName.of('URI'))?.toString().includes('https://example.com/report'), true)
  const dest = annots.map(item => item.lookupMaybe(PDFName.of('Dest'), PDFArray) ?? item.lookupMaybe(PDFName.of('A'), PDFDict)?.lookupMaybe(PDFName.of('D'), PDFArray)).find(Boolean)!
  assert.equal(dest.get(0)?.toString(), output.getPage(1).ref.toString())
  for (const operations of [
    [{ kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 20, 120, 50], url: 'javascript:alert(1)', color, width: 2 }],
    [{ kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 20, 120, 50], url: 'https://a.example', destPage: 1, color, width: 2 }],
    [{ kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 20, 120, 50], color, width: 2 }],
    [{ kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 20, 120, 50], destPage: 3, color, width: 2 }],
    [{ kind: 'deletePage', pageId: second }, { kind: 'addDrawing', pageId: first, shape: 'link', rect: [20, 20, 120, 50], destPage: 2, color, width: 2 }],
    [{ kind: 'addDrawing', pageId: first, shape: 'rect', rect: [20, 20, 120, 50], url: 'https://a.example', color, width: 2 }],
  ]) await assert.rejects(patchPdfWithReceipt(bytes, operations, model.sourceSha256), undefined, JSON.stringify(operations))
})

test('inserted images are written as Stamp annotations; non-PNG data and stray image fields are rejected', async () => {
  const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
  const document = await PDFDocument.create(); document.addPage([400, 500])
  const bytes = await document.save()
  const model = await inspectPdf(bytes)
  const pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [{ kind: 'addDrawing', pageId, shape: 'image', rect: [50, 60, 250, 160], image: png, color, width: 2 }], model.sourceSha256)
  const annots = await annotations(result.bytes)
  assert.deepEqual(annots.map(item => item.get(PDFName.of('Subtype'))?.toString()), ['/Stamp'])
  assert.ok(annots[0]!.get(PDFName.of('AP')))
  for (const operation of [
    { kind: 'addDrawing', pageId, shape: 'image', rect: [50, 60, 250, 160], image: Buffer.from('GIF89a not png').toString('base64'), color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'image', rect: [50, 60, 950, 160], image: png, color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'image', rect: [50, 60, 250, 160], color, width: 2 },
    { kind: 'addDrawing', pageId, shape: 'rect', rect: [50, 60, 250, 160], image: png, color, width: 2 },
  ]) await assert.rejects(patchPdfWithReceipt(bytes, [operation], model.sourceSha256), undefined, JSON.stringify(operation).slice(0, 160))
})


test('measurement preserves Line endpoints, label and resolvable Helvetica appearance; rejects mixed payloads', async () => {
  const document = await PDFDocument.create(); document.addPage([400, 500])
  const bytes = await document.save(), model = await inspectPdf(bytes), pageId = model.pages[0]!.pageId
  const op = { kind: 'addDrawing', pageId, shape: 'measure', from: [250, 300], to: [150, 200], color, width: 2, label: '2.83 m' }
  const result = await patchPdfWithReceipt(bytes, [op], model.sourceSha256)
  const [annot] = await annotations(result.bytes)
  assert.equal(annot!.get(PDFName.of('Subtype'))!.toString(), '/Line')
  assert.equal(annot!.get(PDFName.of('Contents'))!.toString(), '<FEFF0032002E003800330020006D>')
  assert.equal(annot!.get(PDFName.of('L'))!.toString(), '[ 250 300 150 200 ]')
  const ap = annot!.lookup(PDFName.of('AP'), PDFDict).lookup(PDFName.of('N')) as any
  assert.ok(ap.dict.lookup(PDFName.of('Resources'), PDFDict).lookup(PDFName.of('Font'), PDFDict).get(PDFName.of('F1')))
  for (const bad of [{ ...op, label: undefined }, { ...op, label: '米' }, { ...op, label: 'm\n' }, { ...op, shape: 'arrow' }, { ...op, from: [0, -1] }, { ...op, rect: [1, 1, 10, 10] }]) await assert.rejects(patchPdfWithReceipt(bytes, [bad], model.sourceSha256))
})
