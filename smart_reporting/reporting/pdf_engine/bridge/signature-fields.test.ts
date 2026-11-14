import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFString } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

/** 第 1 页两个签名字段：`甲方签字`（未签）与 `已签`（带 /V）；第 2 页无字段。 */
async function source() {
  const document = await PDFDocument.create()
  const page = document.addPage([400, 500]); document.addPage([400, 500])
  page.drawText('Contract body', { x: 30, y: 450 })
  const widget = (name: string, rect: number[], signed: boolean) => {
    const dict = document.context.obj({ FT: 'Sig', T: PDFHexString.fromText(name), Type: 'Annot', Subtype: 'Widget', Rect: rect, F: 4, P: page.ref })
    if (signed) dict.set(PDFName.of('V'), document.context.register(document.context.obj({ Type: 'Sig', Filter: 'Adobe.PPKLite' })))
    return document.context.register(dict)
  }
  const open = widget('甲方签字', [40, 60, 240, 120], false), signed = widget('已签', [260, 60, 380, 120], true)
  page.node.set(PDFName.of('Annots'), document.context.obj([open, signed]))
  document.catalog.set(PDFName.of('AcroForm'), document.context.obj({ Fields: [open, signed], SigFlags: 1 }))
  return document.save()
}
const annotations = async (bytes: Uint8Array) => {
  const page = (await PDFDocument.load(bytes)).getPage(0)
  const list = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
  return Array.from({ length: list?.size() ?? 0 }, (_, index) => list!.lookup(index, PDFDict))
}
const text = (value: unknown) => value instanceof PDFHexString || value instanceof PDFString ? value.decodeText() : undefined

test('签名字段列出控件位置与可放入状态；手写签名放入后带 GenOfficeFormField 关联并重新读为已有可视签名', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [open, signed] = model.signatureFields
  assert.deepEqual(open, { fieldId: open!.fieldId, expectedFieldSha256: open!.expectedFieldSha256, name: '甲方签字', signed: false, visuallySigned: false, widgets: [{ pageIndex: 0, rect: [40, 60, 240, 120] }], bindable: true, reason: null })
  assert.equal(signed!.signed, true); assert.equal(signed!.bindable, false); assert.match(signed!.reason!, /证书签名/)
  const pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'addDrawing', pageId, shape: 'ink', paths: [[60, 80, 120, 110, 200, 70]], color: [0.15, 0.15, 0.15], width: 1.6, signatureField: { fieldId: open!.fieldId, expectedFieldSha256: open!.expectedFieldSha256 } },
  ], model.sourceSha256)
  const ink = (await annotations(result.bytes)).find(item => String(item.get(PDFName.of('Subtype'))) === '/Ink')!
  assert.equal(text(ink.get(PDFName.of('GenOfficeFormField'))), '甲方签字')
  assert.match(text(ink.get(PDFName.of('Contents')))!, /甲方签字$/)
  const reopened = await inspectPdf(result.bytes)
  assert.equal(reopened.signatureFields[0]!.visuallySigned, true)
  assert.equal(reopened.signatureFields[0]!.bindable, false)
  // 签名字段本身不被改写：仍无 /V，控件仍在
  const fieldDict = (await PDFDocument.load(result.bytes)).getForm().getFields().find(field => field.getName() === '甲方签字')!.acroField.dict
  assert.equal(fieldDict.has(PDFName.of('V')), false)
})

test('图像签名同样关联；不带签名字段的普通签名保持原行为', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes), open = model.signatureFields[0]!, pageId = model.pages[0]!.pageId
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'addDrawing', pageId, shape: 'image', image: png, rect: [50, 70, 230, 110], color: [0, 0, 0], width: 2, signatureField: { fieldId: open.fieldId, expectedFieldSha256: open.expectedFieldSha256 } },
    { kind: 'addDrawing', pageId, shape: 'ink', paths: [[20, 300, 80, 330]], color: [0, 0, 0], width: 2 },
  ], model.sourceSha256)
  const list = await annotations(result.bytes)
  assert.equal(text(list.find(item => String(item.get(PDFName.of('Subtype'))) === '/Stamp')!.get(PDFName.of('GenOfficeFormField'))), '甲方签字')
  assert.equal(list.find(item => String(item.get(PDFName.of('Subtype'))) === '/Ink')!.has(PDFName.of('GenOfficeFormField')), false)
})

test('越界、错页、已签、过期身份、重复绑定与非签名形状整批拒绝', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes), [open, signed] = model.signatureFields, pageId = model.pages[0]!.pageId
  const ink = (paths: number[][], field = open!, page = pageId) => ({ kind: 'addDrawing', pageId: page, shape: 'ink', paths, color: [0, 0, 0], width: 1.6, signatureField: { fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256 } })
  await assert.rejects(patchPdfWithReceipt(bytes, [ink([[30, 80, 120, 110]])], model.sourceSha256), /签名字段的范围/)
  await assert.rejects(patchPdfWithReceipt(bytes, [ink([[60, 80, 120, 110]], open, model.pages[1]!.pageId)], model.sourceSha256), /签名字段的范围/)
  await assert.rejects(patchPdfWithReceipt(bytes, [ink([[270, 80, 300, 110]], signed)], model.sourceSha256), /identity_invalid_or_readonly/)
  await assert.rejects(patchPdfWithReceipt(bytes, [{ ...ink([[60, 80, 120, 110]]), signatureField: { fieldId: open!.fieldId, expectedFieldSha256: 'f'.repeat(64) } }], model.sourceSha256), /identity_invalid_or_readonly/)
  await assert.rejects(patchPdfWithReceipt(bytes, [ink([[60, 80, 120, 110]]), ink([[70, 80, 130, 110]])], model.sourceSha256), /identity_invalid_or_readonly/)
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'addDrawing', pageId, shape: 'rect', rect: [50, 70, 100, 100], color: [0, 0, 0], width: 1, signatureField: { fieldId: open!.fieldId, expectedFieldSha256: open!.expectedFieldSha256 } }], model.sourceSha256))
})
