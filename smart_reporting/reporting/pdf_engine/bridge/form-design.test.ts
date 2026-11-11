import assert from 'node:assert/strict'
import { test } from 'node:test'
import { decodePDFRawStream, PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber, PDFRawStream } from 'pdf-lib'
import { inspectDesignWidgets, removeDesignWidget } from './form-design'

async function fixture() {
  const doc = await PDFDocument.create()
  const page = doc.addPage([300, 400])
  page.drawText('unchanged body', { x: 20, y: 350 })
  const form = doc.getForm()
  const name = form.createTextField('name')
  name.addToPage(page, { x: 20, y: 200, width: 120, height: 24 })
  name.setText('Alice')
  form.createCheckBox('keep').addToPage(page, { x: 20, y: 150, width: 20, height: 20 })
  return doc.save()
}

test('strict deletion removes exactly one safe field and its page widget', async () => {
  const bytes = await fixture()
  const census = await inspectDesignWidgets(bytes)
  const target = census.widgets.find(widget => widget.fieldName === 'name')!
  assert.equal(target.removable, true)
  const output = await removeDesignWidget(bytes, census.sourceSha256, target)
  const doc = await PDFDocument.load(output)
  const original = await PDFDocument.load(bytes)
  assert.deepEqual(doc.getForm().getFields().map(field => field.getName()), ['keep'])
  assert.equal(doc.getPage(0).node.Annots()!.size(), 1)
  assert.equal(doc.getForm().getCheckBox('keep').isChecked(), false)
  const beforeContents = original.getPage(0).node.Contents() as PDFArray
  const afterContents = doc.getPage(0).node.Contents() as PDFArray
  for (const ref of beforeContents.asArray()) {
    assert.ok(afterContents.asArray().some(actual => String(actual) === String(ref)))
    assert.equal(doc.context.lookup(ref).toString(), original.context.lookup(ref).toString())
  }
  for (const ref of afterContents.asArray().filter(ref => !beforeContents.asArray().some(old => String(old) === String(ref)))) {
    assert.ok(['q', 'Q'].includes(Buffer.from(decodePDFRawStream(doc.context.lookup(ref, PDFRawStream)).decode()).toString().trim()))
  }
  assert.equal((await inspectDesignWidgets(bytes)).widgets.length, 2)
})

test('forged source, widget identity and dictionary digests never use the upstream name fallback', async () => {
  const bytes = await fixture(), census = await inspectDesignWidgets(bytes)
  const target = census.widgets[0]!
  for (const patch of [{widgetId:'9999R'}, {fieldName:'keep'}, {expectedWidgetSha256:'0'.repeat(64)}, {widgetIdentity:'0'.repeat(64)}]) {
    await assert.rejects(removeDesignWidget(bytes, census.sourceSha256, {...target, ...patch}))
  }
  await assert.rejects(removeDesignWidget(bytes, '0'.repeat(64), target))
})

test('multiple widgets and shared page references remain read only', async () => {
  for (const shared of [false, true]) {
    const doc = await PDFDocument.load(await fixture())
    const name = doc.getForm().getTextField('name')
    if (shared) {
      const first = doc.getPage(0).node.Annots()!.get(0)
      doc.addPage([300,400]).node.set(PDFName.of('Annots'), doc.context.obj([first]))
    } else name.addToPage(doc.getPage(0), { x: 20, y: 100, width: 120, height: 24 })
    const bytes = await doc.save(), census = await inspectDesignWidgets(bytes)
    const targets = census.widgets.filter(widget => widget.fieldName === 'name')
    assert.ok(targets.length > 0)
    for (const target of targets) {
      assert.equal(target.removable, false)
      await assert.rejects(removeDesignWidget(bytes, census.sourceSha256, target))
    }
  }
})

test('protected sources and widget actions remain read only', async () => {
  for (const variant of ['xfa', 'perms', 'signature', 'action', 'locked', 'readonly']) {
    const doc = await PDFDocument.load(await fixture())
    if (variant === 'xfa') doc.catalog.lookup(PDFName.of('AcroForm'), PDFDict).set(PDFName.of('XFA'), doc.context.obj('dynamic'))
    if (variant === 'perms') doc.catalog.set(PDFName.of('Perms'), doc.context.obj({}))
    if (variant === 'signature') doc.context.register(doc.context.obj({Type:'Sig', ByteRange:[0,1,2,3]}))
    if (variant === 'action') doc.getPage(0).node.lookup(PDFName.of('Annots'), PDFArray).lookup(0, PDFDict).set(PDFName.of('AA'), doc.context.obj({}))
    if (variant === 'locked') doc.getPage(0).node.lookup(PDFName.of('Annots'), PDFArray).lookup(0, PDFDict).set(PDFName.of('F'), PDFNumber.of(128))
    if (variant === 'readonly') doc.getForm().getTextField('name').enableReadOnly()
    const bytes = await doc.save(), census = await inspectDesignWidgets(bytes)
    const target = census.widgets.find(widget => widget.fieldName === 'name')!
    assert.equal(target.removable, false)
    await assert.rejects(removeDesignWidget(bytes, census.sourceSha256, target))
  }
})
