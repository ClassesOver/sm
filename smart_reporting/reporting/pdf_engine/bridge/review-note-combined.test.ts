/** 审阅处理必须实际改字并向精确根批注回复，不能冒认作者或父线程。 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './operations'

async function source() {
  const pdf = await PDFDocument.create(), font = await pdf.embedFont(StandardFonts.Helvetica)
  pdf.addPage([300, 300]).drawText('Revenue is 42.', { x: 30, y: 210, size: 12, font })
  const bytes = await pdf.save(), model = await inspectPdf(bytes)
  const note = {kind:'addTextAnnotation',pageId:model.pages[0].pageId,rect:[30,220,50,238],text:'Change revenue to 72.',createdMs:0}
  return (await patchPdfWithReceipt(bytes,[note,note],model.sourceSha256)).bytes
}
function string(dict: PDFDict, key: string) {
  const value = dict.get(PDFName.of(key))
  return value instanceof PDFString || value instanceof PDFHexString ? value.decodeText() : String(value)
}

test('one candidate changes actual text and replies as AI to the exact duplicate-looking original root', async () => {
  const bytes = await source(), model = await inspectPdf(bytes, true), page = model.pages[0]
  const text = page.textObjects.find(item => item.text.includes('42'))!, parent = page.notes[1]
  assert.ok(text); assert.equal(parent.replyable,true)
  const result = await patchPdfWithReceipt(bytes,[
    {kind:'replaceText',pageId:page.pageId,objectId:text.objectId,expectedTextSha256:text.expectedTextSha256,newText:'Revenue is 72.'},
    {kind:'replyNote',pageId:page.pageId,annotationId:parent.annotationId,expectedAnnotationSha256:parent.expectedAnnotationSha256,contents:'Changed revenue to 72.',createdMs:1794355200000,author:'AI Assistant'},
  ],model.sourceSha256)
  assert.deepEqual(result.appliedOperationIndices,[0,1]); assert.deepEqual(result.skippedOperations,[])
  const after = await inspectPdf(result.bytes,true)
  assert.equal(after.pages[0].textObjects.map(item=>item.text).join(''),'Revenue is 72.')
  const output = await PDFDocument.load(result.bytes), annots = output.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  assert.equal(annots.size(),3)
  const reply = annots.lookup(2,PDFDict)
  assert.equal(String(reply.get(PDFName.of('IRT'))),String(annots.get(1)))
  assert.notEqual(String(reply.get(PDFName.of('IRT'))),String(annots.get(0)))
  assert.equal(string(reply,'T'),'AI Assistant')
  assert.equal(string(reply,'Contents'),'Changed revenue to 72.')
})

test('review reply rejects arbitrary authors and stale exact parent identity', async () => {
  const bytes = await source(), model = await inspectPdf(bytes,true), page=model.pages[0], parent=page.notes[1]
  const reply={kind:'replyNote',pageId:page.pageId,annotationId:parent.annotationId,expectedAnnotationSha256:parent.expectedAnnotationSha256,contents:'Need clarification.',createdMs:0}
  await assert.rejects(patchPdfWithReceipt(bytes,[{...reply,author:'Reviewer'}],model.sourceSha256))
  await assert.rejects(patchPdfWithReceipt(bytes,[{...reply,expectedAnnotationSha256:'0'.repeat(64)}],model.sourceSha256),/parent_invalid/)
  const result=await patchPdfWithReceipt(bytes,[reply],model.sourceSha256)
  const output=await PDFDocument.load(result.bytes), annots=output.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  assert.equal(string(annots.lookup(2,PDFDict),'T'),'GenOffice')
})

test('text rewrite rebind rejects changed full parent dictionary and a removed exact reference', async () => {
  const {inspectReplyTargets,rebindTextEditedReplies}=await import('./note-replies')
  const bytes=await source(), original=await PDFDocument.load(bytes), targets=[...inspectReplyTargets(original,'source',false).values()]
  const reply={target:targets[1],contents:'Clarification?',createdMs:0,author:'AI Assistant' as const}
  const changed=await PDFDocument.load(bytes), annots=changed.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  annots.lookup(1,PDFDict).set(PDFName.of('Contents'),PDFString.of('Changed parent'))
  await assert.rejects(rebindTextEditedReplies(bytes,await changed.save(),[reply],[0]),/parent_dictionary_changed/)
  const removed=await PDFDocument.load(bytes)
  removed.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).remove(1)
  await assert.rejects(rebindTextEditedReplies(bytes,await removed.save(),[reply],[0]),/parent_identity_changed/)
  await assert.rejects(rebindTextEditedReplies(bytes,bytes,[{...reply,target:{...reply.target,expectedAnnotationSha256:'0'.repeat(64)}}],[0]),/parent_identity_changed/)
})

test('mixed review preserves imported octal-escaped parent contents with exact reference', async () => {
  const doc=await PDFDocument.load(await source()),annots=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  annots.lookup(1,PDFDict).set(PDFName.of('Contents'),PDFString.of('Change revenue to 72\\056'))
  const bytes=await doc.save(),m=await inspectPdf(bytes,true),p=m.pages[0],t=p.textObjects.find(o=>o.text.includes('42'))!,parent=p.notes[1]
  assert.equal(parent.contents,'Change revenue to 72.')
  const result=await patchPdfWithReceipt(bytes,[{kind:'replaceText',pageId:p.pageId,objectId:t.objectId,expectedTextSha256:t.expectedTextSha256,newText:'Revenue is 72.'},{kind:'replyNote',pageId:p.pageId,annotationId:parent.annotationId,expectedAnnotationSha256:parent.expectedAnnotationSha256,contents:'Changed revenue to 72.',createdMs:0,author:'AI Assistant'}],m.sourceSha256)
  const out=await PDFDocument.load(result.bytes),a=out.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
  assert.equal(String(a.lookup(2,PDFDict).get(PDFName.of('IRT'))),String(a.get(1)))
  assert.equal(string(a.lookup(1,PDFDict),'Contents'),'Change revenue to 72.')
  assert.equal(string(a.lookup(2,PDFDict),'T'),'AI Assistant')
  assert.deepEqual(result.appliedOperationIndices,[0,1])
})

test('text rewrite rebind rejects changed indirect author despite unchanged root ref and dictionary hash',async()=>{
  const {inspectReplyTargets,rebindTextEditedReplies}=await import('./note-replies')
  const doc=await PDFDocument.load(await source()),root=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).lookup(1,PDFDict)
  const authorRef=doc.context.register(PDFString.of('Reviewer'));root.set(PDFName.of('T'),authorRef)
  const bytes=await doc.save(),before=await PDFDocument.load(bytes),target=[...inspectReplyTargets(before,'source',false).values()][1]
  const reply={target,contents:'Clarification?',createdMs:0}
  assert.equal((await rebindTextEditedReplies(bytes,bytes,[reply],[0])).length,1)
  const after=await PDFDocument.load(bytes);after.context.assign(authorRef,PDFString.of('Changed author'))
  await assert.rejects(rebindTextEditedReplies(bytes,await after.save(),[reply],[0]),/parent_dictionary_changed/)
})

test('text rewrite checks actual appearance stream content behind an unchanged reference',async()=>{
  const {inspectReplyTargets,rebindTextEditedReplies}=await import('./note-replies')
  const {PDFRef}=await import('pdf-lib')
  const bytes=await source(),before=await PDFDocument.load(bytes),target=[...inspectReplyTargets(before,'source',false).values()][1]
  const after=await PDFDocument.load(bytes),root=after.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).lookup(1,PDFDict),ref=root.lookup(PDFName.of('AP'),PDFDict).get(PDFName.of('N'))
  assert.ok(ref instanceof PDFRef);after.context.assign(ref,after.context.flateStream('changed annotation appearance'))
  await assert.rejects(rebindTextEditedReplies(bytes,await after.save(),[{target,contents:'Question?',createdMs:0}],[0]),/parent_dictionary_changed/)
})

test('text rewrite bounds indirect author string expansion before building identity arrays',async()=>{
  const {inspectReplyTargets,rebindTextEditedReplies}=await import('./note-replies')
  const doc=await PDFDocument.load(await source()),root=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray).lookup(1,PDFDict)
  root.set(PDFName.of('T'),doc.context.register(PDFString.of('A'.repeat(2000001))))
  const bytes=await doc.save(),before=await PDFDocument.load(bytes),target=[...inspectReplyTargets(before,'source',false).values()][1]
  await assert.rejects(rebindTextEditedReplies(bytes,bytes,[{target,contents:'Question?',createdMs:0}],[0]),/parent_graph_unsupported/)
})
