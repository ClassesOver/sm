import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { assertDocxPageColorWritten, inspectDocxPageColor, validateDocxPageColorOperations } from '../docx-page-color.ts'

const bridge = resolve(import.meta.dirname, '../edit-docx.ts')
const body = '<w:p><w:r><w:t>第一段正文</w:t></w:r></w:p><w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>'
function run(dir: string, request: unknown) {
  const requestPath = join(dir, 'request.json'); writeFileSync(requestPath, JSON.stringify(request))
  return execFileSync(process.execPath, ['--import', 'tsx', bridge, requestPath], { encoding: 'utf8', cwd: resolve(import.meta.dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe'] })
}
async function withBackground(background: string | null) {
  const bytes = await buildDocx({ bodyXml: body })
  if (background === null) return bytes
  const zip = await JSZip.loadAsync(bytes)
  const xml = await zip.file('word/document.xml')!.async('string')
  zip.file('word/document.xml', xml.replace(/(<w:document[^>]*>)/, `$1${background}`))
  return zip.generateAsync({ type: 'uint8array' })
}
const part = async (bytes: Uint8Array, path: string) => (await JSZip.loadAsync(bytes)).file(path)?.async('string') ?? ''

test('inspect classifies sources: none / plain colour editable, theme / VML / duplicate / protected read-only', () => {
  const doc = (inner: string) => `<w:document xmlns:w="w">${inner}<w:body/></w:document>`
  assert.deepEqual({ ...inspectDocxPageColor(doc(''), false), expectedBackgroundSha256: '' }, { color: null, editable: true, readOnlyReason: null, expectedBackgroundSha256: '' })
  assert.equal(inspectDocxPageColor(doc('<w:background w:color="ffe699"/>'), false).color, 'FFE699')
  assert.equal(inspectDocxPageColor(doc('<w:background w:color="FFE699"/>'), false).editable, true)
  for (const background of ['<w:background w:color="FFFFFF" w:themeColor="background1"/>', '<w:background w:color="FF0000"><v:background id="x"/></w:background>',
    '<w:background w:color="auto"/>', '<w:background w:color="FF0000"/><w:background w:color="00FF00"/>']) {
    const model = inspectDocxPageColor(doc(background), false)
    assert.equal(model.editable, false, background); assert.ok(model.readOnlyReason)
  }
  assert.equal(inspectDocxPageColor(doc(''), true).editable, false)
  assert.notEqual(inspectDocxPageColor(doc(''), false).expectedBackgroundSha256, inspectDocxPageColor(doc('<w:background w:color="FF0000"/>'), false).expectedBackgroundSha256)
})

test('validation is batch-first and identity-bound', () => {
  const model = inspectDocxPageColor('<w:document><w:background w:color="FF0000"/><w:body/></w:document>', false)
  const op = { kind: 'setPageColor', expectedBackgroundSha256: model.expectedBackgroundSha256, color: '00B0F0' }
  assert.equal(validateDocxPageColorOperations([], model), undefined)
  assert.equal(validateDocxPageColorOperations([op], model), '00B0F0')
  assert.equal(validateDocxPageColorOperations([{ ...op, color: null }], model), null)
  for (const [bad, code] of [[[op, op], 'batch_conflict'], [[{ ...op, color: '00b0f0' }], 'operation_invalid'], [[{ ...op, color: '#00B0F0' }], 'operation_invalid'],
    [[{ ...op, extra: 1 }], 'operation_invalid'], [[{ ...op, expectedBackgroundSha256: 'f'.repeat(64) }], 'anchor_invalid'], [[{ ...op, color: 'FF0000' }], 'unchanged']] as const) {
    assert.throws(() => validateDocxPageColorOperations(bad as never, model), new RegExp(`docx_page_color_${code}`))
  }
  assert.throws(() => validateDocxPageColorOperations([op], { ...model, editable: false }), /source_unsupported/)
  assert.throws(() => assertDocxPageColorWritten('<w:document><w:body/></w:document>', '', 'FF0000'), /write_not_applied/)
  assert.throws(() => assertDocxPageColorWritten('<w:document><w:background w:color="FF0000"/><w:body/></w:document>', '<w:settings/>', 'FF0000'), /write_not_applied/)
})

test('bridge inspect → set → change → remove through the pinned saveDocx, body bytes unchanged', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-page-color-'))
  try {
    const input = join(dir, 'source.docx'); writeFileSync(input, await withBackground(null))
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    assert.equal(model.capabilities.pageColor, true)
    assert.equal(model.pageColor.color, null); assert.equal(model.pageColor.editable, true)
    const set = join(dir, 'set.docx')
    run(dir, { kind: 'patch', input, output: set, operations: [{ kind: 'setPageColor', expectedBackgroundSha256: model.pageColor.expectedBackgroundSha256, color: 'FFE699' }] })
    const setBytes = readFileSync(set)
    const documentXml = await part(setBytes, 'word/document.xml')
    assert.match(documentXml, /<w:document[^>]*><w:background w:color="FFE699"\/><w:body>/)
    assert.match(await part(setBytes, 'word/settings.xml'), /<w:displayBackgroundShape\/>/)
    const body = (xml: string) => /<w:body>[\s\S]*<\/w:body>/.exec(xml)![0]
    assert.equal(body(documentXml), body(await part(await withBackground(null), 'word/document.xml')))
    const reopened = JSON.parse(run(dir, { kind: 'inspect', input: set }))
    assert.equal(reopened.pageColor.color, 'FFE699')
    // 文字段落修改与页面颜色可同批
    const changed = join(dir, 'changed.docx'), paragraph = reopened.blocks.find((block: { text: string }) => block.text === 'Second paragraph')
    run(dir, { kind: 'patch', input: set, output: changed, operations: [
      { kind: 'setPageColor', expectedBackgroundSha256: reopened.pageColor.expectedBackgroundSha256, color: '0E2841' },
      { kind: 'replaceParagraph', blockId: paragraph.blockId, expectedObjectSha256: paragraph.expectedObjectSha256, text: 'Second paragraph edited' },
    ] })
    const changedModel = JSON.parse(run(dir, { kind: 'inspect', input: changed }))
    assert.equal(changedModel.pageColor.color, '0E2841')
    assert.ok(changedModel.blocks.some((block: { text: string }) => block.text === 'Second paragraph edited'))
    const removed = join(dir, 'removed.docx')
    run(dir, { kind: 'patch', input: changed, output: removed, operations: [{ kind: 'setPageColor', expectedBackgroundSha256: changedModel.pageColor.expectedBackgroundSha256, color: null }] })
    assert.doesNotMatch(await part(readFileSync(removed), 'word/document.xml'), /<w:background/)
    assert.equal(JSON.parse(run(dir, { kind: 'inspect', input: removed })).pageColor.color, null)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('bridge refuses stale identity, read-only sources and mixed special batches without writing output', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-page-color-reject-'))
  try {
    const input = join(dir, 'source.docx'); writeFileSync(input, await withBackground('<w:background w:color="FFFFFF" w:themeColor="background1"/>'))
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    assert.equal(model.pageColor.editable, false)
    const output = join(dir, 'never.docx')
    const attempt = (operations: unknown[]) => assert.throws(() => run(dir, { kind: 'patch', input, output, operations }))
    attempt([{ kind: 'setPageColor', expectedBackgroundSha256: model.pageColor.expectedBackgroundSha256, color: 'FF0000' }])
    const plain = join(dir, 'plain.docx'); writeFileSync(plain, await withBackground(null))
    const plainModel = JSON.parse(run(dir, { kind: 'inspect', input: plain }))
    assert.throws(() => run(dir, { kind: 'patch', input: plain, output, operations: [{ kind: 'setPageColor', expectedBackgroundSha256: 'f'.repeat(64), color: 'FF0000' }] }))
    assert.throws(() => run(dir, { kind: 'patch', input: plain, output, operations: [{ kind: 'setPageColor', expectedBackgroundSha256: plainModel.pageColor.expectedBackgroundSha256, color: 'FF0000' },
      { kind: 'insertCaption', label: 'x' }] }))
    assert.equal(existsSync(output), false)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
