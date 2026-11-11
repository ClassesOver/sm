import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDocument, PDFName, PDFString } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'

async function source() {
  const document = await PDFDocument.create()
  const first = document.addPage([300, 400]); first.drawText('first', { x: 20, y: 300 })
  first.node.set(PDFName.of('Annots'), document.context.obj([document.context.register(document.context.obj({ Type: 'Annot', Subtype: 'Text', Rect: [10, 10, 30, 28], Contents: PDFString.of('keep') }))]))
  document.addPage([500, 250]).drawText('second', { x: 20, y: 100 })
  return document.save()
}

test('blank pages land at the draft position with the requested size, rotation and empty content', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [first, second] = model.pages.map(page => page.pageId)
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'insertBlankPage', pageId: 'blank:a1', width: 300, height: 400 },
    { kind: 'insertBlankPage', pageId: 'blank:b2', width: 612, height: 792 },
    { kind: 'rotatePage', pageId: 'blank:b2', delta: 90 },
    { kind: 'rotatePage', pageId: second, delta: 180 },
    { kind: 'reorderPages', pageIds: ['blank:b2', first, 'blank:a1', second] },
  ], model.sourceSha256)
  assert.deepEqual(result.skippedOperations, [])
  const output = await PDFDocument.load(result.bytes)
  const pages = output.getPages()
  assert.equal(pages.length, 4)
  assert.deepEqual(pages.map(page => [page.getWidth(), page.getHeight(), page.getRotation().angle]), [[612, 792, 90], [300, 400, 0], [300, 400, 0], [500, 250, 180]])
  assert.equal(pages[0]!.node.Contents(), undefined)
  assert.equal(pages[2]!.node.Contents(), undefined)
  // 来源页内容与批注保持原样
  assert.ok(pages[1]!.node.Contents())
  assert.equal(pages[1]!.node.Annots()?.size(), 1)
  const reread = await inspectPdf(result.bytes)
  assert.equal(reread.pageCount, 4)
})

test('blank pages without a reorder are appended after the surviving source pages', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'insertBlankPage', pageId: 'blank:end', width: 200, height: 200 },
    { kind: 'deletePage', pageId: model.pages[0]!.pageId },
  ], model.sourceSha256)
  const pages = (await PDFDocument.load(result.bytes)).getPages()
  assert.deepEqual(pages.map(page => [page.getWidth(), page.getHeight()]), [[500, 250], [200, 200]])
})

test('blank pages reject source-bound edits, duplicates, bad sizes and incomplete orders', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [first, second] = model.pages.map(page => page.pageId)
  const blank = { kind: 'insertBlankPage', pageId: 'blank:x', width: 300, height: 400 }
  const cases: unknown[][] = [
    [blank, { kind: 'cropPage', pageId: 'blank:x', rect: [0, 0, 100, 100] }],
    [blank, { kind: 'highlight', pageId: 'blank:x', rect: [0, 0, 100, 100] }],
    [blank, { kind: 'deletePage', pageId: 'blank:x' }],
    [blank, blank],
    [{ ...blank, width: 0 }],
    [{ ...blank, pageId: 'not-blank' }],
    [{ ...blank, extra: true }],
    [blank, { kind: 'reorderPages', pageIds: [first, second] }],
    [{ kind: 'reorderPages', pageIds: [first, 'blank:x', second] }],
  ]
  for (const operations of cases) await assert.rejects(patchPdfWithReceipt(bytes, operations, model.sourceSha256), undefined, JSON.stringify(operations))
})
