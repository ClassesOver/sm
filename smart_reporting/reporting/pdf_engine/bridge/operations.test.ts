import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { PDFDocument } from 'pdf-lib'
import { inspectPdf } from './operations'

test('an invalid later operation never creates or replaces the output', async () => {
  const document = await PDFDocument.create()
  document.addPage([300, 400])
  const source = await document.save()
  const model = await inspectPdf(source)
  const directory = await mkdtemp(join(tmpdir(), 'pdf-validation-'))
  try {
    const input = join(directory, 'input.pdf'), output = join(directory, 'output.pdf')
    const request = join(directory, 'request.json')
    await writeFile(input, source)
    await writeFile(output, 'untouched')
    await writeFile(request, JSON.stringify({
      kind: 'patch', input, output, sourceSha256: model.sourceSha256,
      operations: [
        { kind: 'rotatePage', pageId: model.pages[0]!.pageId, delta: 90 },
        { kind: 'deletePage', pageId: 'foreign-page' },
      ],
    }))
    const result = spawnSync(process.execPath, ['--import', 'tsx', 'bridge/cli.ts', request], { encoding: 'utf8' })
    assert.notEqual(result.status, 0)
    assert.equal(await readFile(output, 'utf8'), 'untouched')
    assert.deepEqual(await readFile(input), Buffer.from(source))
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('explicit WASM asset paths are resolved without Electron resourcesPath', async () => {
  const { pdfiumWasmPath, hbSubsetWasmPath } = await import('../src/main/wasm-path')
  const previous = process.env.AGENT_REPORTING_PDF_WASM_DIR
  const directory = await mkdtemp(join(tmpdir(), 'pdf-wasm-'))
  try {
    await writeFile(join(directory, 'pdfium.wasm'), 'pdfium')
    await writeFile(join(directory, 'hb-subset.wasm'), 'harfbuzz')
    process.env.AGENT_REPORTING_PDF_WASM_DIR = directory
    assert.equal(pdfiumWasmPath(), join(directory, 'pdfium.wasm'))
    assert.equal(hbSubsetWasmPath(), join(directory, 'hb-subset.wasm'))
    await rm(join(directory, 'pdfium.wasm'))
    assert.throws(pdfiumWasmPath, /PDF WASM/)
  } finally {
    if (previous === undefined) delete process.env.AGENT_REPORTING_PDF_WASM_DIR
    else process.env.AGENT_REPORTING_PDF_WASM_DIR = previous
    await rm(directory, { recursive: true, force: true })
  }
})

test('valid edits cannot overwrite a source through hard-link or path aliases', async () => {
  const { link, symlink } = await import('node:fs/promises')
  const document = await PDFDocument.create()
  document.addPage([300, 400])
  const source = await document.save()
  const model = await inspectPdf(source)
  const directory = await mkdtemp(join(tmpdir(), 'pdf-alias-'))
  try {
    const input = join(directory, 'input.pdf'), alias = join(directory, 'alias.pdf')
    const request = join(directory, 'request.json')
    await writeFile(input, source)
    await link(input, alias)
    const symbolic = join(directory, 'symbolic.pdf')
    await symlink(input, symbolic)
    for (const output of [alias, symbolic, `${directory}/./input.pdf`]) {
      await writeFile(request, JSON.stringify({ kind: 'patch', input, output,
        sourceSha256: model.sourceSha256,
        operations: [{ kind: 'rotatePage', pageId: model.pages[0]!.pageId, delta: 90 }],
      }))
      const result = spawnSync(process.execPath, ['--import', 'tsx', 'bridge/cli.ts', request], { encoding: 'utf8' })
      assert.notEqual(result.status, 0)
      assert.deepEqual(await readFile(input), Buffer.from(source))
    }
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('AcroForm values are bound to source field identity and read back after save', async () => {
  const { inspectPdf, patchPdfWithReceipt } = await import('./operations')
  const document = await PDFDocument.create()
  const page = document.addPage([300, 400])
  const form = document.getForm()
  const text = form.createTextField('contact.name')
  text.addToPage(page, { x: 20, y: 330, width: 180, height: 24 })
  const checkbox = form.createCheckBox('consent')
  checkbox.addToPage(page, { x: 20, y: 290, width: 14, height: 14 })
  const radio = form.createRadioGroup('plan')
  radio.addOptionToPage('basic', page, { x: 20, y: 250, width: 14, height: 14 })
  radio.addOptionToPage('pro', page, { x: 60, y: 250, width: 14, height: 14 })
  const dropdown = form.createDropdown('region')
  dropdown.addOptions(['north', 'south'])
  dropdown.addToPage(page, { x: 20, y: 210, width: 120, height: 24 })
  const source = await document.save()
  const model = await inspectPdf(source)
  assert.equal(model.formFields.length, 4)
  const byName = new Map(model.formFields.map((field) => [field.name, field]))
  assert.equal(byName.get('contact.name')?.kind, 'text')
  assert.equal(byName.get('plan')?.options?.join(','), 'basic,pro')
  const operations = [
    { kind: 'setFormValue', fieldId: byName.get('contact.name')!.fieldId, expectedFieldSha256: byName.get('contact.name')!.expectedFieldSha256, name: 'contact.name', fieldKind: 'text', value: 'Lin' },
    { kind: 'setFormValue', fieldId: byName.get('consent')!.fieldId, expectedFieldSha256: byName.get('consent')!.expectedFieldSha256, name: 'consent', fieldKind: 'checkbox', checked: true },
    { kind: 'setFormValue', fieldId: byName.get('plan')!.fieldId, expectedFieldSha256: byName.get('plan')!.expectedFieldSha256, name: 'plan', fieldKind: 'radio', value: 'pro' },
    { kind: 'setFormValue', fieldId: byName.get('region')!.fieldId, expectedFieldSha256: byName.get('region')!.expectedFieldSha256, name: 'region', fieldKind: 'choice', value: 'south' },
  ]
  const result = await patchPdfWithReceipt(source, operations, model.sourceSha256)
  const reopened = await inspectPdf(result.bytes)
  const fields = new Map(reopened.formFields.map((field) => [field.name, field]))
  assert.equal(fields.get('contact.name')?.value, 'Lin')
  assert.equal(fields.get('consent')?.value, true)
  assert.equal(fields.get('plan')?.value, 'pro')
  assert.equal(fields.get('region')?.value, 'south')
  assert.deepEqual(result.appliedOperationIndices, [0, 1, 2, 3])
  assert.deepEqual(result.skippedOperations, [])
  assert.notEqual(result.sha256, model.sourceSha256)
  assert.equal((await inspectPdf(source)).formFields.find((field) => field.name === 'contact.name')?.value, '')
})

test('AcroForm values reject stale, read-only, forged and duplicate field identities before writing', async () => {
  const { inspectPdf, patchPdfWithReceipt } = await import('./operations')
  const document = await PDFDocument.create()
  const page = document.addPage([300, 400])
  const field = document.getForm().createTextField('readonly')
  field.addToPage(page, { x: 20, y: 330, width: 180, height: 24 })
  field.enableReadOnly()
  const source = await document.save()
  const model = await inspectPdf(source)
  const target = model.formFields[0]!
  assert.equal(target.editable, false)
  const operation = { kind: 'setFormValue', fieldId: target.fieldId, expectedFieldSha256: target.expectedFieldSha256, name: target.name, fieldKind: target.kind, value: 'no' }
  await assert.rejects(() => patchPdfWithReceipt(source, [operation], model.sourceSha256), /只读|unsupported|invalid/i)
  await assert.rejects(() => patchPdfWithReceipt(source, [{ ...operation, fieldId: 'foreign' }], model.sourceSha256), /identity|invalid/i)
  await assert.rejects(() => patchPdfWithReceipt(source, [operation, operation], model.sourceSha256), /重复|duplicate/i)
})

