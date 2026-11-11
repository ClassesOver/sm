import assert from 'node:assert/strict'
import { test } from 'node:test'
import JSZip from 'jszip'
import { parseDocx, saveDocx } from '../../packages/docx-engine/src/index.ts'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { editTableCellShape, tableCellShapeAvailability, verifyTableCellShapeResult } from '../docx-table-cell-shape.ts'
const para = (text: string) => `<w:p w:rsidR="00ABCDEF"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>${text}</w:t></w:r></w:p>`
const cell = (text: string) => `<w:tc><w:tcPr><w:tcW w:w="2001" w:type="dxa"/><w:shd w:fill="EEEEEE"/></w:tcPr>${para(text)}</w:tc>`
const table = `<w:tbl><w:tblPr><w:tblW w:w="4002" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="2001"/><w:gridCol w:w="2001"/></w:tblGrid><w:tr>${cell('A1')}${cell('B1')}</w:tr><w:tr>${cell('A2')}${cell('B2')}</w:tr></w:tbl>`
const rect = { top: 0, left: 0, bottom: 2, right: 2 }
async function open(xml = table) { const parsed = await parseDocx(await buildDocx({ bodyXml: xml })); return { parsed, block: parsed.blocks.find(b => b.type === 'table')! } }
test('真实DOCX合并保留完整原段落字节和阅读顺序，ZIP回读可继续拆分', async () => {
  const { parsed, block } = await open()
  assert.equal(tableCellShapeAvailability(block).cellShapeEditable, true)
  const result = editTableCellShape(block, [{ kind: 'mergeTableCells', rect }])
  for (const value of ['A1', 'B1', 'A2', 'B2']) assert.ok(result.xml.includes(para(value)))
  assert.deepEqual(result.cells[0].paras, ['A1', 'B1', 'A2', 'B2'])
  const bytes = await saveDocx(parsed, [{ kind: 'xml', xml: result.xml }])
  const zip = await JSZip.loadAsync(bytes)
  assert.ok((await zip.file('word/document.xml')!.async('string')).includes(para('B2')))
  const saved = (await parseDocx(bytes)).blocks.find(b => b.type === 'table')!
  assert.equal(tableCellShapeAvailability(saved).cellShapeEditable, true)
  const split = editTableCellShape(saved, [{ kind: 'splitTableCells', rect, rows: 2, columns: 2, mergeFirst: true }])
  assert.equal(split.cells.length, 4)
  assert.deepEqual(split.cells.map(c => c.paras), [['A1', 'B1', 'A2', 'B2'], [''], [''], ['']])
  assert.ok(split.xml.includes(para('A1')))
  assert.equal(split.xml.match(/w:rsidR=/g)?.length, 4)
})
test('普通格拆分扩展邻格跨度，奇数twip分配保持总宽', async () => {
  const { block } = await open()
  const result = editTableCellShape(block, [{ kind: 'splitTableCells', rect: { top: 0, left: 0, bottom: 1, right: 1 }, rows: 3, columns: 2, mergeFirst: false }])
  assert.equal(result.widthsTwips.reduce((a, b) => a + b, 0), 4002)
  assert.equal(result.widthsTwips.length, 3)
  assert.ok(result.cells.some(c => c.top === 0 && c.left === 2 && c.bottom === 3 && c.paras[0] === 'B1'))
  for (const value of ['A1', 'B1', 'A2', 'B2']) assert.ok(result.xml.includes(para(value)))
})
test('拒绝复杂来源与伪造逻辑选区，不放宽原准入', async () => {
  for (const xml of [table.replace(para('A1'), '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>A1</w:t></w:r></w:hyperlink></w:p>'), table.replace('<w:tblPr>', '<w:tblPr><w:bidiVisual/>'), table.replace('<w:tcW ', '<w:tcPrChange w:id="1"/><w:tcW ')]) {
    assert.equal(tableCellShapeAvailability((await open(xml)).block).cellShapeEditable, false)
  }
  const { block } = await open()
  assert.throws(() => editTableCellShape(block, [{ kind: 'mergeTableCells', rect: { ...rect, right: 3 } }]), /cell_shape/)
  assert.throws(() => editTableCellShape(block, [{ kind: 'splitTableCells', rect, rows: 1, columns: 1, mergeFirst: false }]), /cell_shape/)
  assert.throws(() => editTableCellShape(block, [{ kind: 'mergeTableCells', rect, xml: '<w:tbl/>' } as any]), /cell_shape/)
})
test('拒绝带隐藏文字或额外属性的纵向continue，保留来源不静默丢失', async () => {
  const { block } = await open()
  const merged = editTableCellShape(block, [{ kind: 'mergeTableCells', rect }])
  const hidden = merged.xml.replace(/(<w:vMerge\/>[\s\S]*?<\/w:tcPr>)<w:p\/>/, '$1' + para('hidden'))
  const parsed = (await open(hidden)).block
  assert.equal(tableCellShapeAvailability(parsed).cellShapeEditable, false)
})

test('产物回读必须发现原段落属性字节变化、空操作与复杂continue属性', async () => {
  const { block } = await open()
  const result = editTableCellShape(block, [{ kind: 'mergeTableCells', rect }])
  const actual = (await open(result.xml)).block
  verifyTableCellShapeResult(actual, result)
  assert.throws(() => verifyTableCellShapeResult((Object.assign({}, actual, { originalXml: actual.originalXml!.replace('00ABCDEF', '00AAAAAA') })), result), /write_not_applied/)
  const extra = result.xml.replace('<w:vMerge/>', '<w:vMerge/><w:shd w:fill="123456"/>')
  assert.equal(tableCellShapeAvailability((await open(extra)).block).cellShapeEditable, false)
  assert.throws(() => editTableCellShape(block, []), /cell_shape/)
  assert.throws(() => editTableCellShape(block, Array.from({ length: 51 }, () => ({ kind: 'mergeTableCells', rect } as const))), /cell_shape/)
})

test('只更新结构字段，非目标及拆分继承的主题tcPr与原trPr逐字保留', async () => {
  const shd = '<w:shd w:val="pct20" w:color="AABBCC" w:fill="112233" w:themeFill="accent2" w:themeFillTint="99"/>'
  const border = '<w:tcBorders><w:top w:val="double" w:sz="12" w:color="123456" w:themeColor="accent4" w:themeTint="88" w:space="2"/></w:tcBorders>'
  const raw = `<w:tcPr><w:tcW w:w="2001" w:type="dxa"/>${border}${shd}</w:tcPr>`
  const originalCell = cell('B2').replace(/<w:tcPr>[\s\S]*?<\/w:tcPr>/, raw)
  const trPr = '<w:trPr><w:trHeight w:val="401" w:hRule="atLeast"/><w:cantSplit/></w:trPr>'
  const xml = table.replace(cell('B2'), originalCell).replace('<w:tr>', `<w:tr>${trPr}`)
  const { block } = await open(xml)
  const merged = editTableCellShape(block, [{ kind: 'mergeTableCells', rect: { top: 0, left: 0, bottom: 1, right: 2 } }])
  assert.ok(merged.xml.includes(originalCell), '未选中完整cell必须逐字保留')
  assert.ok(merged.xml.includes(trPr), '原行属性必须逐字保留')
  const split = editTableCellShape(block, [{ kind: 'splitTableCells', rect: { top: 1, left: 1, bottom: 2, right: 2 }, rows: 1, columns: 2, mergeFirst: false }])
  assert.equal(split.xml.split(shd).length - 1, 2, '新格继承全部原主题填充字节')
  assert.equal(split.xml.split(border).length - 1, 2, '新格继承全部原主题边框字节')
  const saved = await open(split.xml)
  verifyTableCellShapeResult(saved.block, split)
})

test('pretty XML的非目标完整cell及tcPr间空白保持逐字相等', async () => {
  const prettyCell = cell('B2').replace('<w:tcPr>', '<w:tcPr>\n  ').replace('/><w:shd', '/>\n    <w:shd').replace('</w:tcPr>', '\n</w:tcPr>\n\t').replace('</w:p></w:tc>', '</w:p>\n</w:tc>')
  const { block } = await open(table.replace(cell('B2'), prettyCell))
  const result = editTableCellShape(block, [{ kind: 'mergeTableCells', rect: { top: 0, left: 0, bottom: 1, right: 2 } }])
  assert.ok(result.xml.includes(prettyCell))
})
