import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDocument } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'

async function source(count: number) {
  const document = await PDFDocument.create()
  for (let index = 0; index < count; index++) document.addPage([300, 400]).drawText(`page ${index + 1}`, { x: 20, y: 300 })
  return document.save()
}

test('N-up merge pages and grid split pages write the pinned layouts as a new file', async () => {
  const bytes = await source(5)
  const model = await inspectPdf(bytes)
  const merged = await patchPdfWithReceipt(bytes, [{ kind: 'mergePages', perSheet: 4, direction: 'horizontal', separator: true }], model.sourceSha256)
  const mergedModel = await inspectPdf(merged.bytes)
  assert.equal(mergedModel.pageCount, 2)
  assert.deepEqual(merged.appliedOperationIndices, [0])
  const twoUp = await inspectPdf((await patchPdfWithReceipt(bytes, [{ kind: 'mergePages', perSheet: 2, direction: 'vertical', separator: false }], model.sourceSha256)).bytes)
  assert.equal(twoUp.pageCount, 3)
  assert.deepEqual([twoUp.pages[0]!.mediaBox.width, twoUp.pages[0]!.mediaBox.height], [400, 300], '2-up swaps to landscape')
  const split = await patchPdfWithReceipt(bytes, [{ kind: 'splitPages', perPage: 4 }], model.sourceSha256)
  const splitModel = await inspectPdf(split.bytes)
  assert.equal(splitModel.pageCount, 20)
  assert.deepEqual([splitModel.pages[0]!.cropBox.width, splitModel.pages[0]!.cropBox.height], [150, 200])
  assert.notEqual(merged.previewDigest, split.previewDigest)
  // 同一来源与操作的输出逐字节可复现（预览确认摘要依赖于此）
  await new Promise(resolve => setTimeout(resolve, 1100))
  const again = await patchPdfWithReceipt(bytes, [{ kind: 'mergePages', perSheet: 4, direction: 'horizontal', separator: true }], model.sourceSha256)
  assert.equal(again.sha256, merged.sha256)
  assert.equal(again.previewDigest, merged.previewDigest)
  assert.equal((await patchPdfWithReceipt(bytes, [{ kind: 'splitPages', perPage: 4 }], model.sourceSha256)).sha256, split.sha256)
})

test('layout operations must be saved alone and with valid options', async () => {
  const bytes = await source(2)
  const model = await inspectPdf(bytes)
  const pageId = model.pages[0]!.pageId
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'mergePages', perSheet: 2, direction: 'vertical', separator: false }, { kind: 'rotatePage', pageId, delta: 90 }], model.sourceSha256), /单独保存/)
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'splitPages', perPage: 2 }, { kind: 'splitPages', perPage: 2 }], model.sourceSha256), /单独保存/)
  for (const bad of [{ kind: 'mergePages', perSheet: 1, direction: 'vertical', separator: false }, { kind: 'mergePages', perSheet: 17, direction: 'vertical', separator: false }, { kind: 'mergePages', perSheet: 2, direction: 'diagonal', separator: false }, { kind: 'splitPages', perPage: 3 }, { kind: 'splitPages', perPage: 2, pageId }]) {
    await assert.rejects(patchPdfWithReceipt(bytes, [bad], model.sourceSha256))
  }
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'splitPages', perPage: 2 }], 'f'.repeat(64)), /来源摘要/)
})
