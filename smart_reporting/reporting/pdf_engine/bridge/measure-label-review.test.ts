import assert from 'node:assert/strict'
import { test } from 'node:test'
import { degrees, PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber, PDFRawStream, decodePDFRawStream } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt, sha256 } from './operations'
import { reviewMeasureLabelClipping, type MeasureLabelReviewIssue } from './measure-label-review'

async function source(options: { crop?: number[]; unit?: number; rotation?: number; pages?: number } = {}) {
  const document = await PDFDocument.create()
  for (let i = 0; i < (options.pages ?? 1); i++) {
    const page = document.addPage([500, 600])
    page.drawText('Original target ' + i, { x: 40, y: 500, size: 14 })
    if (options.crop) page.setCropBox(options.crop[0]!, options.crop[1]!, options.crop[2]! - options.crop[0]!, options.crop[3]! - options.crop[1]!)
    if (options.unit) page.node.set(PDFName.of('UserUnit'), PDFNumber.of(options.unit))
    if (options.rotation) page.setRotation(degrees(options.rotation))
  }
  const bytes = await document.save({ useObjectStreams: false })
  return { bytes, model: await inspectPdf(bytes, true) }
}
const drawing = (pageId: string, label = 'W'.repeat(64), from = [330, 200], to = [410, 200]) =>
  ({ kind: 'addDrawing', shape: 'measure', pageId, label, from, to, width: 1, color: [1, 0, 0] })
const cropIssues = (result: Awaited<ReturnType<typeof patchPdfWithReceipt>>) =>
  ('reviewIssues' in result ? result.reviewIssues ?? [] : []).filter(issue => issue.code === 'pdf_measure_label_crop_clipping') as (MeasureLabelReviewIssue & { details: { visibleBox: number[]; clippedEdges: string[]; pageNumber: number } })[]

for (const rotation of [0, 90, 180, 270]) test(`actual cropped UserUnit=2 output warns without changing label at rotation ${rotation}`, async () => {
  const { bytes, model } = await source({ crop: [30, 40, 430, 440], unit: 2, rotation })
  const original = sha256(bytes), op = drawing(model.pages[0]!.pageId)
  const result = await patchPdfWithReceipt(bytes, [op], original)
  assert.deepEqual(result.appliedOperationIndices, [0]); assert.deepEqual(result.skippedOperations, [])
  const issues = cropIssues(result); assert.equal(issues.length, 1)
  assert.equal(issues[0]!.operationIndex, 0); assert.match(issues[0]!.message, /可能.*裁切/)
  assert.deepEqual(issues[0]!.details.visibleBox, [30, 40, 430, 440])
  assert.deepEqual(issues[0]!.details.clippedEdges, ['right'])
  const saved = await PDFDocument.load(result.bytes), page = saved.getPage(0)
  assert.equal(page.getRotation().angle, rotation); assert.equal(page.node.lookup(PDFName.of('UserUnit'), PDFNumber).asNumber(), 2)
  const annotation = page.node.lookup(PDFName.of('Annots'), PDFArray).lookup(0, PDFDict)
  assert.equal(String(annotation.get(PDFName.of('L'))), saved.context.obj([...op.from, ...op.to]).toString())
  const ap = annotation.lookup(PDFName.of('AP'), PDFDict).lookup(PDFName.of('N'), PDFRawStream)
  assert.match(Buffer.from(decodePDFRawStream(ap).decode()).toString(), new RegExp('\\(' + 'W'.repeat(64) + '\\) Tj'))
  assert.equal(sha256(bytes), original); assert.equal(sha256(result.bytes), result.sha256)
})

test('normal label has no crop warning and nonmeasure does not enter review', async () => {
  const { bytes, model } = await source(), pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [drawing(pageId, '3.00 m', [40, 200], [140, 200]),
    { kind: 'addDrawing', shape: 'caret', pageId, point: [60, 60], color: [1, 0, 0], width: 1 }], sha256(bytes))
  assert.deepEqual(cropIssues(result), []); assert.deepEqual(result.appliedOperationIndices, [0, 1])
})

test('review uses actual final crop and output page number after reorder', async () => {
  const { bytes, model } = await source({ pages: 2 }), pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [drawing(pageId, 'W'.repeat(24), [100, 200], [200, 200]),
    { kind: 'cropPage', pageId, rect: [0, 0, 200, 400] },
    { kind: 'reorderPages', pageIds: [model.pages[1]!.pageId, pageId] }], sha256(bytes))
  const issues = cropIssues(result); assert.equal(issues.length, 1)
  assert.equal(issues[0]!.details.pageNumber, 2); assert.deepEqual(issues[0]!.details.visibleBox, [0, 0, 200, 400])
  const output = await PDFDocument.load(result.bytes); assert.equal(output.getPage(1).getCropBox().width, 200)
})

test('visible box intersects MediaBox, and malformed review input becomes a soft failure', async () => {
  const { bytes } = await source({ crop: [-50, -50, 550, 650] })
  const target = { operationIndex: 7, pageIndex: 0, from: [330, 200], to: [410, 200], label: 'W'.repeat(64) }
  const issues = await reviewMeasureLabelClipping(bytes, [target])
  assert.deepEqual((issues[0]!.details as { visibleBox: number[] }).visibleBox, [0, 0, 500, 600])
  const digest = sha256(bytes)
  for (const failed of [await reviewMeasureLabelClipping(new Uint8Array([1]), [target]),
    await reviewMeasureLabelClipping(bytes, [{ ...target, pageIndex: 99 }]),
    await reviewMeasureLabelClipping(bytes, [{ ...target, label: '测' }])]) {
    assert.equal(failed[0]!.operationIndex, 7); assert.equal(failed[0]!.code, 'pdf_measure_label_crop_review_failed')
    assert.match(failed[0]!.message, /实际生成文件已保留/)
  }
  assert.equal(sha256(bytes), digest)
})

test('styled mixed path also reports applied measurement crop risk', async () => {
  const { bytes, model } = await source(), page = model.pages[0]!, target = page.textObjects!.find(t => t.text === 'Original target 0')!
  const result = await patchPdfWithReceipt(bytes, [drawing(page.pageId), {
    kind: 'replaceText', pageId: page.pageId, sourceSha256: sha256(bytes), objectId: target.objectId,
    expectedTextSha256: target.expectedTextSha256, newText: 'Changed target', font: 'courier', fontSize: 12,
  }], sha256(bytes))
  assert.deepEqual(result.appliedOperationIndices, [0, 1]); assert.deepEqual(result.skippedOperations, [])
  assert.equal(cropIssues(result).length, 1); assert.equal(cropIssues(result)[0]!.operationIndex, 0)
  assert.ok(result.previewDigest)
})


test('post-generation review exception retains actual output and all application decisions', async () => {
  const { bytes, model } = await source(), op = drawing(model.pages[0]!.pageId), load = PDFDocument.load
  let injected = false
  try {
    PDFDocument.load = async (...args) => {
      const document = await load.call(PDFDocument, ...args)
      if (document.getPage(0).node.lookupMaybe(PDFName.of('Annots'), PDFArray)?.size()) {
        injected = true
        document.getPage(0).getCropBox = () => { throw Error('injected output crop diagnostics failure') }
      }
      return document
    }
    const result = await patchPdfWithReceipt(bytes, [op], sha256(bytes))
    assert.equal(injected, true); assert.deepEqual(result.appliedOperationIndices, [0]); assert.deepEqual(result.skippedOperations, [])
    assert.ok('reviewIssues' in result)
    assert.equal(result.reviewIssues[0]!.code, 'pdf_measure_label_crop_review_failed')
    assert.equal(result.sha256, sha256(result.bytes)); assert.ok(result.previewDigest)
    PDFDocument.load = load
    const output = await PDFDocument.load(result.bytes)
    assert.equal(output.getPage(0).node.lookup(PDFName.of('Annots'), PDFArray).size(), 1)
  } finally { PDFDocument.load = load }
})

for (const mixed of [false, true]) test(`late crop diagnostic failure cannot change confirmation digest for identical ${mixed ? 'styled' : 'standalone'} output`, async () => {
  const { bytes, model } = await source(), page = model.pages[0]!, target = page.textObjects!.find(t => t.text === 'Original target 0')!
  const ops = [drawing(page.pageId), ...(mixed ? [{
    kind: 'replaceText', pageId: page.pageId, sourceSha256: sha256(bytes), objectId: target.objectId,
    expectedTextSha256: target.expectedTextSha256, newText: 'Changed target', font: 'courier', fontSize: 12,
  }] : [])]
  const normal = await patchPdfWithReceipt(bytes, ops, sha256(bytes)), load = PDFDocument.load
  assert.equal(cropIssues(normal).length, 1)
  let injected = 0
  try {
    PDFDocument.load = async (...args) => {
      // Fault only the post-generation diagnostic, after prior writer/content
      // identity checks. This does not fabricate a replacement receipt/digest.
      const inCropDiagnostic = new Error().stack?.includes('reviewMeasureLabelClipping')
      const document = await load.call(PDFDocument, ...args)
      if (inCropDiagnostic) {
        injected++
        document.getPage(0).getCropBox = () => { throw Error('late crop review unavailable') }
      }
      return document
    }
    const changedReview = await patchPdfWithReceipt(bytes, ops, sha256(bytes))
    assert.equal(injected, 1)
    assert.deepEqual(changedReview.appliedOperationIndices, normal.appliedOperationIndices)
    assert.deepEqual(changedReview.skippedOperations, normal.skippedOperations)
    assert.deepEqual(changedReview.bytes, normal.bytes)
    assert.equal(changedReview.sha256, normal.sha256)
    assert.ok('reviewIssues' in changedReview)
    assert.equal(changedReview.reviewIssues.filter(issue => issue.code === 'pdf_measure_label_crop_review_failed').length, 1)
    assert.equal(cropIssues(changedReview).length, 0)
    assert.equal(changedReview.previewDigest, normal.previewDigest)
  } finally { PDFDocument.load = load }
})
