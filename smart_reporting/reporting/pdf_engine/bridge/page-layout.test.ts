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

test('N-up preserves measurement and filled widget appearances as static content; split refuses forms', async () => {
  const {inspectNativeText}=await import('./text-operations')
  const {createHash}=await import('node:crypto')
  const doc=await PDFDocument.create(),page=doc.addPage([400,500]);page.drawText('body',{x:40,y:350})
  const field=doc.getForm().createTextField('customer');field.addToPage(page,{x:40,y:200,width:120,height:20});field.setText('Alice')
  let bytes=await doc.save(), model=await inspectPdf(bytes)
  bytes=(await patchPdfWithReceipt(bytes,[{kind:'addDrawing',pageId:model.pages[0]!.pageId,shape:'measure',from:[40,100],to:[240,100],label:'2.00 m',color:[1,0,0],width:2}],model.sourceSha256)).bytes
  model=await inspectPdf(bytes)
  const op={kind:'mergePages',perSheet:2,direction:'horizontal',separator:false}
  const result=await patchPdfWithReceipt(bytes,[op],model.sourceSha256)
  const content=(await inspectNativeText(result.bytes,createHash('sha256').update(result.bytes).digest('hex'))).flat().map(text=>text.text).join(' ')
  assert.ok(content.includes('Alice') && content.includes('2.00 m'),content)
  await new Promise(resolve=>setTimeout(resolve,1100))
  assert.equal((await patchPdfWithReceipt(bytes,[op],model.sourceSha256)).sha256,result.sha256)
  await assert.rejects(patchPdfWithReceipt(bytes,[{kind:'splitPages',perPage:2}],model.sourceSha256),/表单字段/)
})

test('dynamic XFA sources are refused instead of silently losing their form content',async()=>{
  const {PDFName,PDFString}=await import('pdf-lib')
  const doc=await PDFDocument.create();doc.addPage([300,400])
  doc.catalog.set(PDFName.of('AcroForm'),doc.context.obj({Fields:[],XFA:PDFString.of('<xdp/>')}))
  const bytes=await doc.save(),model=await inspectPdf(bytes)
  for(const op of [{kind:'mergePages',perSheet:2,direction:'horizontal',separator:false},{kind:'splitPages',perPage:2}]) await assert.rejects(patchPdfWithReceipt(bytes,[op],model.sourceSha256),/动态表单/)
})

test('N-up uses the visible CropBox, nonzero origin, rotation and physical UserUnit',async()=>{
  const {PDFName,PDFNumber,degrees}=await import('pdf-lib')
  for(const [angle,unit,expected] of [[0,1,[250,200]],[90,2,[400,500]]] as const){
    const doc=await PDFDocument.create(),page=doc.addPage([400,500]);page.drawText('visible',{x:100,y:300})
    page.setCropBox(50,100,200,250);page.setRotation(degrees(angle));page.node.set(PDFName.of('UserUnit'),PDFNumber.of(unit))
    const bytes=await doc.save(),model=await inspectPdf(bytes)
    const output=await patchPdfWithReceipt(bytes,[{kind:'mergePages',perSheet:2,direction:'horizontal',separator:false}],model.sourceSha256)
    const saved=(await inspectPdf(output.bytes)).pages[0]!
    assert.deepEqual([saved.mediaBox.width,saved.mediaBox.height],expected)
  }
})

test('unconfirmed form appearances are refused rather than flattening stale field values',async()=>{
  const {PDFName,PDFBool}=await import('pdf-lib')
  const doc=await PDFDocument.create(),page=doc.addPage([300,400]);doc.getForm().createTextField('name').addToPage(page,{x:20,y:30,width:100,height:20})
  doc.getForm().acroForm.dict.set(PDFName.of('NeedAppearances'),PDFBool.True)
  const bytes=await doc.save(),model=await inspectPdf(bytes)
  await assert.rejects(patchPdfWithReceipt(bytes,[{kind:'mergePages',perSheet:2,direction:'horizontal',separator:false}],model.sourceSha256),/表单外观/)
})
