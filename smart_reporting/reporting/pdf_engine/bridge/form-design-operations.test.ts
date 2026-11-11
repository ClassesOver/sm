import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDocument } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt, sha256 } from './operations'

async function fixture() {
  const doc = await PDFDocument.create(), page = doc.addPage([300, 400])
  page.drawText('unchanged body', {x:20,y:350})
  const field = doc.getForm().createTextField('remove_me')
  field.addToPage(page, {x:20,y:200,width:120,height:24})
  doc.getForm().createCheckBox('keep').addToPage(page, {x:20,y:150,width:20,height:20})
  return doc.save()
}

test('native operation removes exact widget with reproducible output and preview receipt', async () => {
  const bytes = await fixture(), model = await inspectPdf(bytes)
  assert.equal(model.capabilities.removeFormWidget, true)
  const widget = model.formDesignWidgets.find(widget => widget.fieldName === 'remove_me')!
  const op = {kind:'removeFormWidget',sourceSha256:model.sourceSha256,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256}
  const receipt = await patchPdfWithReceipt(bytes, [op], model.sourceSha256)
  assert.deepEqual(receipt.appliedOperationIndices, [0])
  assert.deepEqual(receipt.skippedOperations, [])
  assert.equal(receipt.sha256, sha256(receipt.bytes))
  assert.equal(receipt.size, receipt.bytes.length)
  assert.match(receipt.previewDigest, /^[a-f0-9]{64}$/)
  const output = await inspectPdf(receipt.bytes)
  assert.deepEqual(output.formFields.map(field => field.name), ['keep'])
  assert.deepEqual(output.formDesignWidgets.map(widget => widget.fieldName), ['keep'])
  assert.equal((await patchPdfWithReceipt(bytes, [op], model.sourceSha256)).previewDigest, receipt.previewDigest)
})

test('native form design refuses mixed operations, forged identities and unexpected fields', async () => {
  const bytes = await fixture(), model = await inspectPdf(bytes)
  const widget = model.formDesignWidgets[0]!
  const op = {kind:'removeFormWidget',sourceSha256:model.sourceSha256,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256}
  for (const operations of [[op,op], [op,{kind:'rotatePage',pageId:model.pages[0].pageId,delta:90}], [{...op,sourceSha256:'0'.repeat(64)}], [{...op,widgetIdentity:'0'.repeat(64)}], [{...op,extra:true}]]) {
    await assert.rejects(patchPdfWithReceipt(bytes, operations, model.sourceSha256))
  }
  await assert.rejects(patchPdfWithReceipt(bytes, [op], '0'.repeat(64)))
})
