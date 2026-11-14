import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { DOCX_TABLE_PRESETS } from '../docx-table-style.ts'

const bridge = resolve(import.meta.dirname, '../edit-docx.ts')
const cell = (text: string) => `<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>${text}</w:t></w:r></w:p></w:tc>`
const row = (...texts: string[]) => `<w:tr>${texts.map(cell).join('')}</w:tr>`
const table = `<w:tbl><w:tblPr><w:tblStyle w:val="LightGrid"/><w:tblW w:w="6000" w:type="dxa"/><w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid><w:gridCol w:w="3000"/><w:gridCol w:w="3000"/></w:tblGrid>${row('项目', '金额')}${row('收入', '100')}${row('成本', '60')}</w:tbl>`
const body = `<w:p><w:r><w:t>前文</w:t></w:r></w:p>${table}<w:p><w:r><w:t>后文</w:t></w:r></w:p>`
const styles = '<w:style w:type="table" w:styleId="LightGrid"><w:name w:val="Light Grid"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/></w:tblBorders></w:tblPr></w:style><w:style w:type="table" w:styleId="MediumShading"><w:name w:val="Medium Shading 1"/></w:style>'

function run(dir: string, request: unknown) {
  const path = join(dir, 'request.json')
  writeFileSync(path, JSON.stringify(request))
  return execFileSync(process.execPath, ['--import', 'tsx', bridge, path], { encoding: 'utf8', cwd: resolve(import.meta.dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe'] })
}
const tableXml = async (bytes: Uint8Array) => /<w:tbl>[\s\S]*<\/w:tbl>/.exec(await (await JSZip.loadAsync(bytes)).file('word/document.xml')!.async('string'))![0]
async function fixture() {
  const dir = mkdtempSync(join(tmpdir(), 'docx-table-style-')), input = join(dir, 'source.docx')
  writeFileSync(input, await buildDocx({ bodyXml: body, extraStylesXml: styles }))
  const model = JSON.parse(run(dir, { kind: 'inspect', input }))
  const block = model.blocks.find((item: { type: string }) => item.type === 'table')
  const op = (fields: Record<string, unknown>) => ({ kind: 'setTableStyle', blockId: block.blockId, expectedObjectSha256: block.expectedObjectSha256, ...fields })
  return { dir, input, model, block, op }
}
const look = { firstRow: true, lastRow: true, firstColumn: false, lastColumn: false, bandedRows: false, bandedColumns: true }

test('inspect reports the document table styles and the table style state', async () => {
  const { dir, model, block } = await fixture()
  try {
    assert.deepEqual(model.tableStyles, [{ styleId: 'LightGrid', name: 'Light Grid' }, { styleId: 'MediumShading', name: 'Medium Shading 1' }])
    assert.equal(block.tableStyleEditable, true)
    assert.deepEqual(block.tableStyleState, { styleId: 'LightGrid', look: { firstRow: true, lastRow: false, firstColumn: true, lastColumn: false, bandedRows: true, bandedColumns: false }, presetEditable: true })
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('document style, no style and table style options write tblStyle/tblLook and keep rows byte-identical', async () => {
  const { dir, input, op } = await fixture()
  try {
    const source = await tableXml(readFileSync(input))
    const styled = join(dir, 'styled.docx')
    run(dir, { kind: 'patch', input, output: styled, operations: [op({ styleId: 'MediumShading', look })] })
    const xml = await tableXml(readFileSync(styled))
    assert.ok(xml.includes('<w:tblPr><w:tblStyle w:val="MediumShading"/><w:tblW w:w="6000" w:type="dxa"/><w:tblLook w:val="0260" w:firstRow="1" w:lastRow="1" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="0"/></w:tblPr>'), xml)
    assert.equal(xml.slice(xml.indexOf('<w:tblGrid>')), source.slice(source.indexOf('<w:tblGrid>')))
    const reread = JSON.parse(run(dir, { kind: 'inspect', input: styled })).blocks.find((item: { type: string }) => item.type === 'table')
    assert.deepEqual(reread.tableStyleState.look, look)
    assert.equal(reread.tableStyleState.styleId, 'MediumShading')
    const plain = join(dir, 'plain.docx')
    run(dir, { kind: 'patch', input, output: plain, operations: [op({ styleId: null })] })
    const plainXml = await tableXml(readFileSync(plain))
    assert.doesNotMatch(plainXml, /w:tblStyle/)
    assert.ok(plainXml.includes('w:val="04A0"'), 'look untouched when only the style changes')
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('built-in presets apply the pinned header/band fills and single borders and drop tblStyle', async () => {
  const { dir, input, op } = await fixture()
  try {
    const output = join(dir, 'preset.docx')
    run(dir, { kind: 'patch', input, output, operations: [op({ preset: 'blueBanded' })] })
    const xml = await tableXml(readFileSync(output)), preset = DOCX_TABLE_PRESETS.blueBanded
    assert.doesNotMatch(xml, /w:tblStyle/)
    const fills = [...xml.matchAll(/<w:tc>[\s\S]*?<\/w:tc>/g)].map(match => /w:fill="([0-9A-Fa-f]{6})"/.exec(match[0])?.[1]?.toUpperCase() ?? null)
    // 首行 headerFill；第 2 行（index 1，奇数）band1；第 3 行（index 2，偶数）band2
    assert.deepEqual(fills, [preset.headerFill, preset.headerFill, preset.band1Fill, preset.band1Fill, preset.band2Fill, preset.band2Fill])
    assert.equal((xml.match(/w:val="single" w:sz="4"[^>]*w:color="9DC3E6"/g) ?? []).length >= 24, true, xml)
    assert.match(xml, /<w:t>收入<\/w:t>/)
    const grid = join(dir, 'grid.docx')
    run(dir, { kind: 'patch', input, output: grid, operations: [op({ preset: 'grid', look })] })
    const gridXml = await tableXml(readFileSync(grid))
    assert.doesNotMatch(gridXml, /w:shd/)
    assert.match(gridXml, /w:noHBand="1"/)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('stale, unknown, mixed and conflicting requests are rejected without output', async () => {
  const { dir, input, op, block } = await fixture()
  try {
    const output = join(dir, 'never.docx')
    const bad = [op({ styleId: 'Missing' }), op({ preset: 'rainbow' }), op({ preset: 'grid', styleId: null }), op({}), op({ look: { ...look, extra: true } }), op({ look: { firstRow: true } }),
      { ...op({ styleId: null }), expectedObjectSha256: 'f'.repeat(64) }, op({ styleId: null, extra: 1 })]
    for (const item of bad) assert.throws(() => run(dir, { kind: 'patch', input, output, operations: [item] }), undefined, JSON.stringify(item))
    assert.throws(() => run(dir, { kind: 'patch', input, output, operations: [op({ styleId: null }), { kind: 'setTableAlignment', blockId: block.blockId, expectedObjectSha256: block.expectedObjectSha256, alignment: 'center' }] }))
    assert.equal(existsSync(output), false)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('merged cells keep style/look editable and presets follow the cell shading capability', async () => {
  const merged = table.replace(`${row('项目', '金额')}`, '<w:tr><w:tc><w:tcPr><w:tcW w:w="6000" w:type="dxa"/><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>合并</w:t></w:r></w:p></w:tc></w:tr>')
  const dir = mkdtempSync(join(tmpdir(), 'docx-table-style-')), input = join(dir, 'merged.docx')
  try {
    writeFileSync(input, await buildDocx({ bodyXml: merged, extraStylesXml: styles }))
    const block = JSON.parse(run(dir, { kind: 'inspect', input })).blocks.find((item: { type: string }) => item.type === 'table')
    assert.equal(block.tableStyleEditable, true)
    const op = (fields: Record<string, unknown>) => ({ kind: 'setTableStyle', blockId: block.blockId, expectedObjectSha256: block.expectedObjectSha256, ...fields })
    if (!block.tableStyleState.presetEditable) assert.throws(() => run(dir, { kind: 'patch', input, output: join(dir, 'x.docx'), operations: [op({ preset: 'blueHeader' })] }))
    run(dir, { kind: 'patch', input, output: join(dir, 'ok.docx'), operations: [op({ look })] })
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
