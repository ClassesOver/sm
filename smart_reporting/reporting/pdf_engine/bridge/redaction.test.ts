import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { PDFDocument, rgb } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'
import { inspectNativeText } from './text-operations'

const texts = async (bytes: Uint8Array) => (await inspectNativeText(bytes, createHash('sha256').update(bytes).digest('hex'))).map(page => page.map(object => object.text).join(' '))

async function source() {
  const document = await PDFDocument.create()
  const first = document.addPage([300, 400])
  first.drawText('SECRET-ALPHA', { x: 20, y: 300, size: 14 })
  first.drawText('public-alpha', { x: 20, y: 200, size: 14 })
  first.drawRectangle({ x: 150, y: 50, width: 60, height: 40, color: rgb(0.2, 0.4, 0.8) })
  const second = document.addPage([300, 400])
  second.drawText('SECRET-BETA', { x: 20, y: 300, size: 14 })
  second.drawText('public-beta', { x: 20, y: 200, size: 14 })
  return document.save()
}

test('redaction removes the covered text permanently and keeps the rest of the page', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [p1] = model.pages
  const result = await patchPdfWithReceipt(bytes, [
    { kind: 'addDrawing', pageId: p1!.pageId, shape: 'rect', rect: [140, 40, 220, 100], color: [1, 0, 0], width: 2 },
    { kind: 'redact', pageId: p1!.pageId, rect: [15, 290, 200, 320] },
  ], model.sourceSha256)
  const after = await texts(result.bytes)
  assert.ok(!after[0]!.includes('SECRET'), after[0])
  assert.ok(after[0]!.includes('public-alpha'))
  assert.ok(after[1]!.includes('SECRET-BETA'), 'other pages untouched')
  assert.ok(!Buffer.from(result.bytes).includes('SECRET-ALPHA'), 'no residual bytes of the redacted text')
  assert.equal((await inspectPdf(result.bytes)).pageCount, 2)
})

test('redaction follows the final page order after reorder and delete', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [p1, p2] = model.pages
  const reordered = await patchPdfWithReceipt(bytes, [
    { kind: 'reorderPages', pageIds: [p2!.pageId, p1!.pageId] },
    { kind: 'redact', pageId: p1!.pageId, rect: [15, 290, 200, 320] },
  ], model.sourceSha256)
  assert.deepEqual((await texts(reordered.bytes)).map(text => text.includes('SECRET')), [true, false])
  assert.ok((await texts(reordered.bytes))[0]!.includes('SECRET-BETA'))
  const deleted = await patchPdfWithReceipt(bytes, [
    { kind: 'deletePage', pageId: p1!.pageId },
    { kind: 'redact', pageId: p2!.pageId, rect: [15, 290, 200, 320] },
  ], model.sourceSha256)
  const remaining = await texts(deleted.bytes)
  assert.equal(remaining.length, 1)
  assert.ok(!remaining[0]!.includes('SECRET') && remaining[0]!.includes('public-beta'))
})

test('redaction rejects out-of-page, degenerate, blank-page, deleted-page and page-size combinations', async () => {
  const bytes = await source()
  const model = await inspectPdf(bytes)
  const [p1] = model.pages
  for (const rect of [[0, 0, 0.5, 10], [-5, 0, 50, 50], [10, 10, 400, 50]] as [number, number, number, number][]) {
    await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'redact', pageId: p1!.pageId, rect }], model.sourceSha256), /涂黑范围无效/)
  }
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'redact', pageId: p1!.pageId, rect: [10, 10, 50, 50], extra: 1 } as never], model.sourceSha256))
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'deletePage', pageId: p1!.pageId }, { kind: 'redact', pageId: p1!.pageId, rect: [10, 10, 50, 50] }], model.sourceSha256))
  await assert.rejects(patchPdfWithReceipt(bytes, [{ kind: 'setPageSize', preset: 'A4' }, { kind: 'redact', pageId: p1!.pageId, rect: [10, 10, 50, 50] }], model.sourceSha256), /页面尺寸/)
  await assert.rejects(patchPdfWithReceipt(bytes, [
    { kind: 'insertBlankPage', pageId: 'blank:x', width: 300, height: 400 },
    { kind: 'redact', pageId: 'blank:x', rect: [10, 10, 50, 50] },
  ], model.sourceSha256), /空白页/)
  // 同批裁切后只能涂黑可见范围
  await assert.rejects(patchPdfWithReceipt(bytes, [
    { kind: 'cropPage', pageId: p1!.pageId, rect: [0, 100, 300, 400] },
    { kind: 'redact', pageId: p1!.pageId, rect: [10, 10, 50, 50] },
  ], model.sourceSha256), /涂黑范围无效/)
})

test('redaction refuses root annotations reachable by outside replies, but keeps exclusive notes supported', async () => {
  const { PDFArray, PDFName, PDFString } = await import('pdf-lib')
  const doc=await PDFDocument.create(), page=doc.addPage([400,500])
  const root=doc.context.register(doc.context.obj({Type:'Annot',Subtype:'Text',Rect:[40,100,60,120],Contents:PDFString.of('CONFIDENTIAL_ROOT')}))
  const reply=doc.context.register(doc.context.obj({Type:'Annot',Subtype:'Text',Rect:[250,250,270,270],Contents:PDFString.of('outside'),IRT:root,RT:'R'}))
  page.node.set(PDFName.of('Annots'),doc.context.obj([root,reply]))
  const bytes=await doc.save(), model=await inspectPdf(bytes)
  await assert.rejects(patchPdfWithReceipt(bytes,[{kind:'redact',pageId:model.pages[0]!.pageId,rect:[30,90,80,130]}],model.sourceSha256),/关联批注/)
  page.node.set(PDFName.of('Annots'),doc.context.obj([root]));doc.context.delete(reply)
  const single=await doc.save(), sm=await inspectPdf(single)
  const clean=await patchPdfWithReceipt(single,[{kind:'redact',pageId:sm.pages[0]!.pageId,rect:[30,90,80,130]}],sm.sourceSha256)
  assert.ok(!Buffer.from(clean.bytes).includes('CONFIDENTIAL_ROOT'))
  assert.equal((await PDFDocument.load(clean.bytes)).getPage(0).node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.size() ?? 0,0)
})

test('redaction refuses a hit annotation whose appearance stream is shared outside the area', async()=>{
  const {PDFName}=await import('pdf-lib')
  const doc=await PDFDocument.create(),page=doc.addPage([400,500])
  const ap=doc.context.register(doc.context.stream('0 0 20 20 re f',{Type:'XObject',Subtype:'Form',BBox:[0,0,20,20]}))
  const annotations=[[40,100,60,120],[250,250,270,270]].map(Rect=>doc.context.register(doc.context.obj({Type:'Annot',Subtype:'Square',Rect,AP:{N:ap}})))
  page.node.set(PDFName.of('Annots'),doc.context.obj(annotations))
  const bytes=await doc.save(),model=await inspectPdf(bytes)
  await assert.rejects(patchPdfWithReceipt(bytes,[{kind:'redact',pageId:model.pages[0]!.pageId,rect:[30,90,80,130]}],model.sourceSha256),/关联批注/)
})
