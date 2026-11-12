import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { assertDocxWatermarkWritten, validateDocxWatermarkOperations, type DocxWatermarkModel } from '../docx-watermark.ts'

const bridge = resolve(import.meta.dirname, '../edit-docx.ts')
const body = '<w:p><w:r><w:t>第一段正文</w:t></w:r></w:p><w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>'
function run(dir: string, request: unknown) {
  const requestPath = join(dir, 'request.json'); writeFileSync(requestPath, JSON.stringify(request))
  return execFileSync(process.execPath, ['--import', 'tsx', bridge, requestPath], { encoding: 'utf8', cwd: resolve(import.meta.dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe'] })
}
const zipOf = (bytes: Uint8Array) => JSZip.loadAsync(bytes)
const headers = async (bytes: Uint8Array) => { const zip = await zipOf(bytes); return Promise.all(Object.keys(zip.files).filter(name => /^word\/header\d*\.xml$/.test(name)).sort().map(async name => [name, await zip.file(name)!.async('string')] as const)) }
const bodyOf = async (bytes: Uint8Array) => /<w:body>[\s\S]*<\/w:body>/.exec(await (await zipOf(bytes)).file('word/document.xml')!.async('string'))![0].replace(/<w:sectPr\b[\s\S]*<\/w:sectPr>/, '')

test('validation is batch-first, identity-bound and limited to the pinned dialog values', () => {
  const model: DocxWatermarkModel = { text: null, style: null, picture: false, mixed: false, editable: true, readOnlyReason: null, expectedHeadersSha256: 'a'.repeat(64) }
  const op = { kind: 'setWatermark', expectedHeadersSha256: model.expectedHeadersSha256, watermark: { text: '机密' } }
  assert.equal(validateDocxWatermarkOperations([], model), undefined)
  assert.deepEqual(validateDocxWatermarkOperations([op], model), { text: '机密' })
  const full = { text: 'DRAFT', fontFamily: '宋体', colorHex: 'FF0000', opacity: 0.35, diagonal: false, bold: true, italic: true, sizePt: 72, boxPt: { widthPt: 240.5, heightPt: 52.1 } }
  assert.deepEqual(validateDocxWatermarkOperations([{ ...op, watermark: full }], model), full)
  for (const [bad, code] of [
    [[op, op], 'batch_conflict'], [[{ ...op, extra: 1 }], 'operation_invalid'], [[{ ...op, expectedHeadersSha256: 'f'.repeat(64) }], 'anchor_invalid'],
    [[{ ...op, watermark: null }], 'unchanged'], [[{ ...op, watermark: { text: '' } }], 'operation_invalid'], [[{ ...op, watermark: { text: ' 机密 ' } }], 'operation_invalid'],
    [[{ ...op, watermark: { text: 'a\nb' } }], 'operation_invalid'], [[{ ...op, watermark: { text: 'x'.repeat(256) } }], 'operation_invalid'],
    [[{ ...op, watermark: { text: 'x', colorHex: '#FF0000' } }], 'operation_invalid'], [[{ ...op, watermark: { text: 'x', colorHex: 'ff0000' } }], 'operation_invalid'],
    [[{ ...op, watermark: { text: 'x', opacity: 1.5 } }], 'operation_invalid'], [[{ ...op, watermark: { text: 'x', opacity: 0.333 } }], 'operation_invalid'],
    [[{ ...op, watermark: { text: 'x', sizePt: 72 } }], 'operation_invalid'], [[{ ...op, watermark: { text: 'x', sizePt: 70, boxPt: { widthPt: 1, heightPt: 1 } } }], 'operation_invalid'],
    [[{ ...op, watermark: { text: 'x', fontFamily: 'a"b' } }], 'operation_invalid'], [[{ ...op, watermark: { text: 'x', diagonal: 'yes' } }], 'operation_invalid'],
    [[{ ...op, watermark: { text: 'x', image: {} } }], 'operation_invalid'],
  ] as const) assert.throws(() => validateDocxWatermarkOperations(bad as never, model), new RegExp(`docx_watermark_${code}`), JSON.stringify(bad))
  assert.equal(validateDocxWatermarkOperations([{ ...op, watermark: null }], { ...model, text: '草稿' }), null)
  assert.throws(() => validateDocxWatermarkOperations([op], { ...model, editable: false }), /source_unsupported/)
  assert.throws(() => assertDocxWatermarkWritten([['word/header1.xml', '<w:hdr/>']], [['word/header1.xml', '<w:hdr/>']], { text: 'x' }), /write_not_applied/)
})

test('bridge creates, restyles and removes the text watermark through the pinned saveDocx; body unchanged', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-watermark-'))
  try {
    const source = await buildDocx({ bodyXml: body })
    const input = join(dir, 'source.docx'); writeFileSync(input, source)
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    assert.equal(model.capabilities.watermark, true)
    assert.deepEqual({ ...model.watermark, expectedHeadersSha256: '' }, { text: null, style: null, picture: false, mixed: false, editable: true, readOnlyReason: null, expectedHeadersSha256: '' })
    const set = join(dir, 'set.docx')
    run(dir, { kind: 'patch', input, output: set, operations: [{ kind: 'setWatermark', expectedHeadersSha256: model.watermark.expectedHeadersSha256, watermark: { text: '机密' } }] })
    const setBytes = readFileSync(set)
    const [[, header]] = await headers(setBytes)
    assert.match(header, /<w:docPartGallery w:val="Watermarks"\/>/)
    assert.match(header, /<v:textpath style="[^"]*" string="机密"\/>/)
    assert.match(header, /rotation:315/)
    assert.equal(await bodyOf(setBytes), await bodyOf(source))
    const reopened = JSON.parse(run(dir, { kind: 'inspect', input: set }))
    assert.equal(reopened.watermark.text, '机密')
    assert.deepEqual(reopened.watermark.style, { fontFamily: 'DengXian', colorHex: 'C0C0C0', opacity: 0.5, diagonal: true })
    // 自定义：字体、颜色、透明度、水平、粗体、固定字号；正文段落修改可同批
    const styled = join(dir, 'styled.docx'), paragraph = reopened.blocks.find((block: { text: string }) => block.text === 'Second paragraph')
    run(dir, { kind: 'patch', input: set, output: styled, operations: [
      { kind: 'setWatermark', expectedHeadersSha256: reopened.watermark.expectedHeadersSha256, watermark: { text: 'DRAFT', fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.3, diagonal: false, bold: true, sizePt: 72, boxPt: { widthPt: 233.5, heightPt: 52 } } },
      { kind: 'replaceParagraph', blockId: paragraph.blockId, expectedObjectSha256: paragraph.expectedObjectSha256, text: 'Second paragraph edited' },
    ] })
    const [[, styledHeader]] = await headers(readFileSync(styled))
    assert.match(styledHeader, /string="DRAFT"/)
    assert.match(styledHeader, /width:233\.5pt;height:52pt;z-index/)
    assert.doesNotMatch(styledHeader, /rotation:315/)
    assert.match(styledHeader, /fillcolor="#C00000"/)
    assert.match(styledHeader, /<v:fill opacity="0\.3"\/>/)
    assert.match(styledHeader, /font-family:&quot;Arial&quot;;font-size:1pt;font-weight:bold/)
    const styledModel = JSON.parse(run(dir, { kind: 'inspect', input: styled }))
    assert.equal(styledModel.watermark.text, 'DRAFT')
    assert.deepEqual(styledModel.watermark.style, { fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.3, diagonal: false, bold: true })
    assert.ok(styledModel.blocks.some((block: { text: string }) => block.text === 'Second paragraph edited'))
    const removed = join(dir, 'removed.docx')
    run(dir, { kind: 'patch', input: styled, output: removed, operations: [{ kind: 'setWatermark', expectedHeadersSha256: styledModel.watermark.expectedHeadersSha256, watermark: null }] })
    for (const [, xml] of await headers(readFileSync(removed))) assert.doesNotMatch(xml, /<v:textpath|Watermarks/)
    assert.equal(JSON.parse(run(dir, { kind: 'inspect', input: removed })).watermark.text, null)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('existing header text is kept; stale identity, protection and header batches are refused without output', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-watermark-reject-'))
  try {
    const input = join(dir, 'source.docx'); writeFileSync(input, await buildDocx({ bodyXml: body, headerXml: '<w:p><w:r><w:t>页眉原文</w:t></w:r></w:p>' }))
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    const kept = join(dir, 'kept.docx')
    run(dir, { kind: 'patch', input, output: kept, operations: [{ kind: 'setWatermark', expectedHeadersSha256: model.watermark.expectedHeadersSha256, watermark: { text: '样本' } }] })
    const [[name, xml]] = await headers(readFileSync(kept))
    assert.equal(name, 'word/header1.xml')
    assert.match(xml, /页眉原文/); assert.match(xml, /string="样本"/)
    const output = join(dir, 'never.docx')
    assert.throws(() => run(dir, { kind: 'patch', input, output, operations: [{ kind: 'setWatermark', expectedHeadersSha256: 'f'.repeat(64), watermark: { text: '样本' } }] }))
    const hf = model.sections.at(-1).headersFooters.parts['header.default']
    assert.equal(hf.text, '页眉原文')
    for (const other of [{ kind: 'setHeaderFooter', sectionId: model.sections.at(-1).sectionId, part: 'header', variant: 'default', expectedPartSha256: hf.expectedPartSha256, text: '新页眉' },
      { kind: 'setSectionLayout', sectionId: model.sections.at(-1).sectionId, values: { orientation: 'landscape' } }]) {
      assert.throws(() => run(dir, { kind: 'patch', input, output, operations: [{ kind: 'setWatermark', expectedHeadersSha256: model.watermark.expectedHeadersSha256, watermark: { text: '样本' } }, other] }),
        (error: { stderr?: string }) => /docx_watermark_header_batch_conflict/.test(String(error.stderr)))
    }
    const zip = await JSZip.loadAsync(readFileSync(input))
    zip.file('word/settings.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:documentProtection w:edit="readOnly" w:enforcement="1"/></w:settings>')
    const protectedInput = join(dir, 'protected.docx'); writeFileSync(protectedInput, await zip.generateAsync({ type: 'uint8array' }))
    const protectedModel = JSON.parse(run(dir, { kind: 'inspect', input: protectedInput }))
    assert.equal(protectedModel.watermark.editable, false); assert.ok(protectedModel.watermark.readOnlyReason)
    assert.throws(() => run(dir, { kind: 'patch', input: protectedInput, output, operations: [{ kind: 'setWatermark', expectedHeadersSha256: protectedModel.watermark.expectedHeadersSha256, watermark: { text: '样本' } }] }))
    assert.equal(existsSync(output), false)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
