import assert from 'node:assert/strict'
import { test } from 'node:test'
import JSZip from 'jszip'
import { parseDocx, saveDocx } from '../../packages/docx-engine/src/index.ts'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { editTableColumnWidths, tableColumnWidthAvailability, verifyTableColumnWidthResult } from '../docx-table-column-width.ts'
const p = '<w:p w:rsidR="00112233"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>same</w:t></w:r></w:p>'
const props = '<w:shd w:val="pct20" w:themeFill="accent2" w:fill="123456"/><w:tcBorders><w:top w:val="double" w:themeColor="accent4" w:space="2"/></w:tcBorders>'
const cell = (w: number, rest = '', body = p) => `<w:tc><w:tcPr><w:tcW w:w = '${w}' w:type="dxa"/>${rest}${props}</w:tcPr>${body}</w:tc>`
const xml = `<w:tbl><w:tblPr><w:tblW w:w="5401" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr>\n<w:tblGrid><w:gridCol w:w="2401"/><w:gridCol w:w="3000"/></w:tblGrid>\n<w:tr>${cell(5401, '<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>')}</w:tr>\n<w:tr>${cell(5401, '<w:gridSpan w:val="2"/><w:vMerge/>', '<w:p w:rsidR="99887766"><w:r><w:t>hidden continuation</w:t></w:r></w:p>')}</w:tr></w:tbl>`
async function open(value = xml) { const parsed = await parseDocx(await buildDocx({ bodyXml: value })); return { parsed, block: parsed.blocks.find(b => b.type === 'table')! } }
test('real DOCX merged widths preserve all nonwidth bytes including complex continuation', async () => {
  const { parsed, block } = await open()
  assert.equal(tableColumnWidthAvailability(block, 9000).columnWidthEditable, true)
  const result = editTableColumnWidths(block, 9000, [{ kind: 'distributeTableColumns', left: 0, right: 2 }])
  assert.deepEqual(result.widthsTwips, [2701, 2700])
  const scrub = (s: string) => s.replace(/(w:w\s*=\s*["'])\d+/g, '$1WIDTH')
  assert.equal(scrub(result.xml), scrub(block.originalXml!))
  const bytes = await saveDocx(parsed, [{ kind: 'xml', xml: result.xml }])
  const actual = (await parseDocx(bytes)).blocks.find(b => b.type === 'table')!
  verifyTableColumnWidthResult(actual, result)
  const before = await JSZip.loadAsync(await buildDocx({ bodyXml: xml })), after = await JSZip.loadAsync(bytes)
  for (const path of Object.keys(before.files)) if (!before.files[path].dir && path !== 'word/document.xml') assert.deepEqual(await after.file(path)!.async('uint8array'), await before.file(path)!.async('uint8array'))
})
test('set synchronizes table total and every span width, allows repeated reopened edits', async () => {
  const { parsed, block } = await open()
  const result = editTableColumnWidths(block, 9000, [{ kind: 'setTableColumnWidth', left: 0, right: 1, widthTwips: 3000 }])
  assert.deepEqual(result.widthsTwips, [3000, 3000])
  assert.ok(result.xml.includes('w:w="6000"'))
  assert.equal(result.xml.match(/w:w = '6000'/g)?.length, 2)
  const saved = (await parseDocx(await saveDocx(parsed, [{ kind: 'xml', xml: result.xml }]))).blocks.find(b => b.type === 'table')!
  assert.deepEqual(editTableColumnWidths(saved, 9000, [{ kind: 'distributeTableColumns', left: 1, right: 2 }]).widthsTwips, [3000, 3000])
})
test('rejects ambiguous geometry and forged steps without an output', async () => {
  for (const value of [xml.replace('<w:tr>', '<w:tr><w:trPr><w:gridBefore w:val="1"/></w:trPr>'), xml.replace('w:val="restart"', 'w:val="continue"'), xml.replace('w:type="fixed"', 'w:type="autofit"')]) assert.equal(tableColumnWidthAvailability((await open(value)).block, 9000).columnWidthEditable, false)
  const { block } = await open()
  assert.throws(() => editTableColumnWidths(block, 9000, [{ kind: 'distributeTableColumns', left: 0, right: 2, xml: 'forged' } as any]))
  assert.throws(() => editTableColumnWidths(block, 0, [{ kind: 'distributeTableColumns', left: 0, right: 2 }]))
})
test('preserves nested objects as opaque XML when only their outer width changes', async () => {
  const nested = '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w="1000" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>nested</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
  const { block } = await open(xml.replace(p, p + nested + '<w:p/>'))
  assert.equal(tableColumnWidthAvailability(block, 9000).columnWidthEditable, true)
  const result = editTableColumnWidths(block, 9000, [{ kind: 'setTableColumnWidth', left: 0, right: 1, widthTwips: 3000 }])
  assert.ok(result.xml.includes(nested))
  assert.ok(result.xml.includes('hidden continuation'))
})
test('refuses malformed XML, orphan spans, pct widths, duplicate attrs and readonly layouts', async () => {
  const { block } = await open()
  for (const originalXml of [xml + '<bad>', xml.replace('w:val="restart"', 'w:val="continue"'), xml.replace('w:type="dxa"', 'w:type="pct"'), xml.replace('w:w="5401"', 'w:w="5401" w:w="5401"'), xml.replace('<w:tblPr>', '<w:tblPr><w:tblpPr w:leftFromText="1"/>'), xml.replace('<w:tblPr>', '<w:tblPr><w:bidiVisual/>')]) assert.equal(tableColumnWidthAvailability({ ...block, originalXml }, 9000).columnWidthEditable, false)
  const result = editTableColumnWidths(block, 9000, [{ kind: 'distributeTableColumns', left: 0, right: 2 }])
  assert.throws(() => verifyTableColumnWidthResult({ ...block, originalXml: result.xml.replace('00112233', '00112234') }, result))
})
test('rejects unknown geometry wrappers/leaf attributes and nonempty width leaves', async () => {
  const { block } = await open()
  const invalid = [
    xml.replace('<w:tblGrid>', '<w:tblGrid w:unknown="1">'),
    xml.replace('<w:tcPr>', '<w:tcPr w:unknown="1">'),
    xml.replace('<w:shd w:val="pct20" w:themeFill="accent2" w:fill="123456"/>', '<w:shd w:val="pct20"><w:tcW w:w="999" w:type="dxa"/></w:shd>'),
    xml.replace('<w:gridCol w:w="2401"/>', '<w:gridCol w:w="2401" w:bogus="1"/>'),
    xml.replace('<w:gridCol w:w="2401"/>', '<w:gridCol w:w="2401"><w:gridCol w:w="999"/></w:gridCol>'),
    xml.replace('<w:tblPr>', '<w:tblPr><w:unknown><w:tblW w:w="1" w:type="dxa"/></w:unknown>'),
    xml.replace('<w:tblPr>', '<w:tblPr><w:tblInd w:w="1440" w:type="dxa"/>'),
    xml.replace('<w:tblPr>', '<w:tblPr><w:tblCellSpacing w:w="100" w:type="dxa"/>'),
    xml.replace('<w:tcPr>', '<w:tcPr><w:tcFitText/>'),
    xml.replace('<w:tr>', '<w:tr><w:trPr><w:tblCellSpacing w:w="100" w:type="dxa"/></w:trPr>'),
    xml.replace('w:type="fixed"/>', 'w:type="fixed"><w:bogus/></w:tblLayout>'),
    xml.replace('w:val="2"/>', 'w:val="2" w:unknown="1"/>'),
    xml.replace('w:val="restart"/>', 'w:val="restart">bad</w:vMerge>'),
    xml.replace("w:type=\"dxa\"/>", "w:type=\"dxa\" w:unknown=\"1\"/>")
  ]
  for (const originalXml of invalid) assert.equal(tableColumnWidthAvailability({ ...block, originalXml }, 9000).columnWidthEditable, false, originalXml)
})
test('does not reject or normalize opaque paragraph formatting and content attributes', async () => {
  const originalXml = xml.replace('<w:pPr>', '<w:pPr><w:contextualSpacing/><w:suppressAutoHyphens/>').replace('w:rsidR="00112233"', 'w:rsidR="00112233" w:custom="opaque"')
  const { block } = await open(originalXml)
  assert.equal(tableColumnWidthAvailability(block, 9000).columnWidthEditable, true)
  const result = editTableColumnWidths(block, 9000, [{ kind: 'distributeTableColumns', left: 0, right: 2 }])
  assert.ok(result.xml.includes('<w:contextualSpacing/><w:suppressAutoHyphens/>'))
  assert.ok(result.xml.includes('w:custom="opaque"'))
})
