import assert from 'node:assert/strict'
import { test } from 'node:test'
import JSZip from 'jszip'
import { parseDocx, saveDocx } from '../../packages/docx-engine/src/index.ts'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { editTableRowHeights, tableRowHeightAvailability, verifyTableRowHeightResult } from '../docx-table-row-height.ts'
const p = '<w:p w:rsidR="00112233"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>same</w:t></w:r></w:p>'
const cell = (merge: string, body = p) => `<w:tc><w:tcPr><w:tcW w:w="4800" w:type="dxa"/><w:gridSpan w:val="2"/><w:vMerge ${merge}/><w:shd w:themeFill="accent2"/></w:tcPr>${body}</w:tc>`
const h = '<w:trHeight w:val = \'300\' w:hRule="exact"/>'
const other = '<w:cantSplit/>  <w:tblHeader/>'
const xml = `<w:tbl><w:tblPr><w:tblW w:w="4800" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="2400"/><w:gridCol w:w="2400"/></w:tblGrid>\n<w:tr w:rsidR="ABCDEF00"><w:trPr>\n ${h}  ${other}\n</w:trPr>${cell('w:val="restart"')}</w:tr>\n<w:tr><w:trPr><w:cantSplit/></w:trPr>${cell('', '<w:p><w:r><w:t>hidden continuation</w:t></w:r></w:p>')}</w:tr></w:tbl>`
async function open(value = xml) { const bytes = await buildDocx({ bodyXml: value }); const parsed = await parseDocx(bytes); return { bytes, parsed, block: parsed.blocks.find(b => b.type === 'table')! } }
test('real merged DOCX set/clear only changes direct height while retaining all other XML and ZIP parts', async () => {
  const { bytes, parsed, block } = await open()
  assert.equal(tableRowHeightAvailability(block, 1000).rowHeightEditable, true)
  const result = editTableRowHeights(block, 1000, [{ top: 0, bottom: 2, heightTwips: 600 }, { top: 1, bottom: 2, heightTwips: null }])
  assert.equal(result.xml, block.originalXml!.replace("w:val = '300'", "w:val = '600'"))
  assert.deepEqual(result.rowHeightsTwips, [600, null]); assert.deepEqual(result.rowHeightRules, ['exact', null])
  const output = await saveDocx(parsed, [{ kind: 'xml', xml: result.xml }])
  verifyTableRowHeightResult((await parseDocx(output)).blocks.find(b => b.type === 'table')!, result)
  const before = await JSZip.loadAsync(bytes), after = await JSZip.loadAsync(output)
  for (const path of Object.keys(before.files)) if (!before.files[path].dir && path !== 'word/document.xml') assert.deepEqual(await after.file(path)!.async('uint8array'), await before.file(path)!.async('uint8array'))
  const cleared = editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: null }])
  assert.equal(cleared.xml, block.originalXml!.replace(h, ''))
})
test('adds height without rebuilding absent/selfclosing trPr, preserves omitted rule, sequential clear loses old exact', async () => {
  for (const trPr of ['', '<w:trPr/>']) {
    const { block } = await open(xml.replace(`<w:trPr>\n ${h}  ${other}\n</w:trPr>`, trPr))
    const result = editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: 2000 }])
    assert.ok(result.xml.includes('<w:trHeight w:val="1000" w:hRule="atLeast"/>'))
  }
  const { block } = await open(xml.replace(' w:hRule="exact"', ''))
  const result = editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: 600 }])
  assert.equal(result.xml, block.originalXml!.replace("w:val = '300'", "w:val = '600'"))
  assert.deepEqual(result.rowHeightRules, ['atLeast', null])
  const original = (await open()).block
  const sequential = editTableRowHeights(original, 1000, [{ top: 0, bottom: 1, heightTwips: null }, { top: 0, bottom: 1, heightTwips: 500 }])
  assert.ok(sequential.xml.includes('w:hRule="atLeast"')); assert.deepEqual(sequential.rowHeightRules, ['atLeast', null])
})
test('rejects unknown/duplicate/nested source height and invalid steps before mutation', async () => {
  const { block } = await open()
  for (const value of [h.replace('/>', ' w:unknown="1"/>'), h + h, '<w:unknown>' + h + '</w:unknown>', h.replace('/>', '>x</w:trHeight>'), h.replace('exact', 'bogus'), h.replace("'300'", "'-1'"), h.replace("'300'", "'300' w:val=\"300\"")]) assert.equal(tableRowHeightAvailability({ ...block, originalXml: block.originalXml!.replace(h, value) }, 1000).rowHeightEditable, false)
  assert.throws(() => editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: 1, xml: 'forged' } as any]))
})
test('rejects trPr attributes/hidden height and orphan merge while permitting opaque paragraphs', async () => {
  const { block } = await open()
  for (const originalXml of [block.originalXml!.replace('<w:trPr>', '<w:trPr w:unknown="1">'), block.originalXml!.replace('<w:cantSplit/>', '<w:cantSplit>' + h + '</w:cantSplit>'), block.originalXml!.replace('w:val="restart"', 'w:val="continue"')]) assert.equal(tableRowHeightAvailability({ ...block, originalXml }, 1000).rowHeightEditable, false)
  const opaque = (await open(xml.replace('<w:keepNext/>', '<w:keepNext/><w:contextualSpacing/>'))).block
  assert.ok(editTableRowHeights(opaque, 1000, [{ top: 0, bottom: 1, heightTwips: 500 }]).xml.includes('<w:keepNext/><w:contextualSpacing/>'))
})
test('rejects an explicitly empty hRule rather than treating it as omitted', async () => {
  const { block } = await open(xml.replace('w:hRule="exact"', 'w:hRule=""'))
  assert.equal(tableRowHeightAvailability(block, 1000).rowHeightEditable, false)
})
test('supports source auto and zero heights with normalized PM semantics and surgical set/clear', async () => {
  for (const [sourceHeight, effective, rule] of [
    ['<w:trHeight w:val="300" w:hRule="auto"/>', 300, 'atLeast'],
    ['<w:trHeight w:val="0" w:hRule="auto"/>', null, null],
    ['<w:trHeight w:val="0"/>', null, null],
  ] as const) {
    const { parsed, block } = await open(xml.replace(h, sourceHeight))
    const capability = tableRowHeightAvailability(block, 1000)
    assert.equal(capability.rowHeightEditable, true)
    assert.equal(capability.rowHeightsTwips[0], effective); assert.equal(capability.rowHeightRules[0], rule)
    const set = editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: 600 }])
    assert.equal(set.xml, block.originalXml!.replace(sourceHeight, '<w:trHeight w:val="600" w:hRule="atLeast"/>'))
    verifyTableRowHeightResult((await parseDocx(await saveDocx(parsed, [{ kind: 'xml', xml: set.xml }]))).blocks.find(b => b.type === 'table')!, set)
    const clear = editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: null }])
    assert.equal(clear.xml, block.originalXml!.replace(sourceHeight, ''))
    assert.equal(clear.rowHeightsTwips[0], null); assert.equal(clear.rowHeightRules[0], null)
    const untouched = editTableRowHeights(block, 1000, [{ top: 1, bottom: 2, heightTwips: 500 }])
    assert.ok(untouched.xml.includes(sourceHeight))
  }
})
test('distribute forces atLeast surgically and mixed set/clear never revives exact', async () => {
  const { bytes, parsed, block } = await open()
  const result = editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, heightTwips: 400 }, { kind: 'distributeTableRows', top: 0, bottom: 1, heightTwips: 2000 }])
  assert.equal(result.xml, block.originalXml!.replace("w:val = '300'", "w:val = '2000'").replace('w:hRule="exact"', 'w:hRule="atLeast"'))
  assert.deepEqual(result.rowHeightRules, ['atLeast', null]); assert.deepEqual(result.rowHeightsTwips, [2000, null])
  const output = await saveDocx(parsed, [{ kind: 'xml', xml: result.xml }]); verifyTableRowHeightResult((await parseDocx(output)).blocks.find(b => b.type === 'table')!, result)
  const before = await JSZip.loadAsync(bytes), after = await JSZip.loadAsync(output)
  for (const path of Object.keys(before.files)) if (!before.files[path].dir && path !== 'word/document.xml') assert.deepEqual(await after.file(path)!.async('uint8array'), await before.file(path)!.async('uint8array'))
  for (const clear of [false, true]) {
    const ordered = editTableRowHeights(block, 1000, [{ kind: 'distributeTableRows', top: 0, bottom: 1, heightTwips: 450 }, ...(clear ? [{ top: 0, bottom: 1, heightTwips: null }] : []), { top: 0, bottom: 1, heightTwips: 600 }])
    assert.deepEqual(ordered.rowHeightRules, ['atLeast', null]); assert.ok(ordered.xml.includes('w:hRule="atLeast"')); assert.ok(!ordered.xml.includes('w:hRule="exact"'))
  }
  for (const declared of ['', ' w:hRule="auto"', ' w:hRule="atLeast"']) {
    const source = (await open(xml.replace(' w:hRule="exact"', declared))).block
    const edited = editTableRowHeights(source, 1000, [{ kind: 'distributeTableRows', top: 0, bottom: 1, heightTwips: 450 }])
    assert.deepEqual(edited.rowHeightRules, ['atLeast', null]); assert.equal(edited.xml, source.originalXml!.replace("w:val = '300'", "w:val = '450'").replace('w:hRule="auto"', 'w:hRule="atLeast"'))
  }
})
test('distribute rejects unknown fields, kind and null instead of accepting arbitrary rules', async () => {
  const { block } = await open()
  for (const extra of [{ kind: 'distributeTableRows', heightTwips: null }, { kind: 'distributeTableRows', heightTwips: 0 }, { kind: 'distributeTableRows', heightTwips: 1.5 }, { kind: 'distributeTableRows', heightTwips: 31681 }, { kind: 'other', heightTwips: 500 }, { kind: 'distributeTableRows', heightTwips: 500, heightRule: 'exact' }]) assert.throws(() => editTableRowHeights(block, 1000, [{ top: 0, bottom: 1, ...extra }] as any))
})
