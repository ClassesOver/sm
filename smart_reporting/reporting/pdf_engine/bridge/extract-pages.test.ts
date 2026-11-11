import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { PDFDocument, PDFName } from 'pdf-lib'
import { extractPagesBytes } from '../src/main/save-pdf'

async function source() {
  const document = await PDFDocument.create()
  document.addPage([300, 400]).drawText('first')
  document.addPage([500, 250]).drawText('second')
  document.addPage([612, 792]).drawText('third')
  return document.save()
}

test('extracts selected pages in requested order without changing the source', async () => {
  const bytes = await source()
  const sourceSha256 = createHash('sha256').update(bytes).digest('hex')
  const extracted = await extractPagesBytes(bytes, [2, 0])
  const output = await PDFDocument.load(extracted)

  assert.deepEqual(output.getPages().map(page => [page.getWidth(), page.getHeight()]), [[612, 792], [300, 400]])
  assert.equal(createHash('sha256').update(bytes).digest('hex'), sourceSha256)
})

test('rejects empty, duplicate, non-integer and out-of-range page selections', async () => {
  const bytes = await source()
  for (const pages of [[], [1, 1], [1.5], [-1], [3]]) {
    await assert.rejects(extractPagesBytes(bytes, pages), undefined, JSON.stringify(pages))
  }
})

test('rejects protected or annotated source graphs rather than copying incomplete field and reply trees', async () => {
  for (const kind of ['field', 'annotation', 'permissions']) {
    const document = await PDFDocument.load(await source())
    if (kind === 'field') document.getForm().createTextField('name').addToPage(document.getPage(0), {x: 10, y: 10, width: 60, height: 20})
    else if (kind === 'annotation') document.getPage(0).node.set(PDFName.of('Annots'), document.context.obj([document.context.register(document.context.obj({Type: 'Annot', Subtype: 'Text', Rect: [10, 10, 30, 28]}))]))
    else document.catalog.set(PDFName.of('Perms'), document.context.obj({}))
    await assert.rejects(extractPagesBytes(await document.save(), [0]), /pdf_extract_source_unsupported/)
  }
})
