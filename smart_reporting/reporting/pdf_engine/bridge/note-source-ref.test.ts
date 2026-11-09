import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PDFDocument, PDFName, PDFRef, PDFHexString } from 'pdf-lib'
import { inspectPdf, patchPdf, sha256 } from './operations'
test('display reference preserves generation, ordinal identities and direct-note readonly boundary', async () => {
  const doc = await PDFDocument.create(), page = doc.addPage([300,400])
  const dict = () => doc.context.obj({ Type:'Annot', Subtype:'Text', Rect:[30,100,50,118], Contents:PDFHexString.fromText('same') })
  const nonzero = PDFRef.of(80,3); doc.context.assign(nonzero,dict())
  const zero = doc.context.register(dict())
  page.node.set(PDFName.of('Annots'),doc.context.obj([nonzero,zero,dict()]))
  const source = await doc.save({useObjectStreams:false,updateFieldAppearances:false}), model = await inspectPdf(source)
  const notes = model.pages[0].notes
  assert.equal(notes[0].sourceRef,'80R3'); assert.equal(notes[1].sourceRef,`${zero.objectNumber}R`); assert.equal(notes[2].sourceRef,null)
  assert.equal(new Set(notes.map(note=>note.annotationId)).size,3); assert.equal(notes[2].editable,false)
  await assert.rejects(patchPdf(source,[{kind:'editNote',pageId:model.pages[0].pageId,annotationId:notes[0].annotationId,expectedAnnotationSha256:notes[0].expectedAnnotationSha256,contents:'changed',modifiedAt:'2026-11-09T00:00:00Z',sourceRef:notes[0].sourceRef}],sha256(source)))
})
