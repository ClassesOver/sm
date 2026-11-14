import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import JSZip from 'jszip'
import { parseDocx, saveDocx, generateTableModelXml, type TableModel } from '../../packages/docx-engine/src/index.ts'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import * as lifecycle from '../docx-table-lifecycle.ts'

const hash = (xml: string) => createHash('sha256').update(xml).digest('hex')
const model: TableModel = { rows: ['A', 'B', 'C'].map(text => [{ paras: [text], richParas: [{ runs: [{ text }] }] }]), colWidthsTwips: [2000], colWidthsPct: [100], autoFit: 'fixed' }
const generated = generateTableModelXml(model)
const table = generated.replace('<w:tbl>', '<w:tbl w:rsidR="11223344">').replace('</w:tblPr>', '<w:tblCaption w:val="title"/><w:tblDescription w:val="description"/></w:tblPr>').replace('<w:p>', '<w:p w:rsidR="AABBCCDD"><w:pPr><w:keepNext/></w:pPr>')
const open = async (bodyXml = table) => { const bytes = await buildDocx({ bodyXml }); const parsed = await parseDocx(bytes); return { bytes, parsed, block: parsed.blocks.find(b => b.type === 'table')! } }
const context = (block: { originalXml?: string }) => ({ blockId: 'source-table-1', expectedObjectSha256: hash(block.originalXml!), protectedDocument: false })
const operation = (block: { originalXml?: string }, row?: number) => ({ kind: row === undefined ? 'deleteTable' : 'splitTable', blockId: 'source-table-1', expectedObjectSha256: hash(block.originalXml!), ...(row === undefined ? {} : { row }) })

test('lifecycle interface is available', () => { assert.equal(typeof lifecycle.tableLifecycleAvailability, 'function'); assert.equal(typeof lifecycle.editDocxTableLifecycle, 'function') })
test('split preserves exact row, paragraph, style and grid XML; clears lower identity and alt text', async () => {
 const { bytes, parsed, block } = await open(); assert.equal(lifecycle.tableLifecycleAvailability(block, false).tableLifecycleEditable, true)
 const result = lifecycle.editDocxTableLifecycle(block, operation(block, 1), context(block))
 assert.equal(result.kind, 'splitTable'); assert.equal(result.sourceXml, block.originalXml)
 const rows = block.originalXml!.match(/<w:tr>[\s\S]*?<\/w:tr>/g)!
 const prefix = block.originalXml!.slice(0, block.originalXml!.indexOf(rows[0]))
 const lowerPrefix = prefix.replace('<w:tbl w:rsidR="11223344">', '<w:tbl>').replace('<w:tblCaption w:val="title"/>', '').replace('<w:tblDescription w:val="description"/>', '')
 assert.equal(result.replacementXml, prefix + rows[0] + '</w:tbl><w:p/>' + lowerPrefix + rows.slice(1).join('') + '</w:tbl>')
 const output = await saveDocx(parsed, [{ kind: 'xml', docxIndex: block.docxIndex!, xml: result.replacementXml }])
 const reopened = await parseDocx(output), tables = reopened.blocks.filter(b => b.type === 'table')
 assert.deepEqual(tables.map(t => t.table!.rows.map(row => row[0].paras[0])), [['A'], ['B', 'C']]); assert.equal(tables[0].table!.caption, 'title'); assert.ok(!tables[1].table!.caption)
 const a = await JSZip.loadAsync(bytes), b = await JSZip.loadAsync(output)
 for (const name of Object.keys(a.files)) if (!a.files[name].dir && name !== 'word/document.xml') assert.deepEqual(await a.file(name)!.async('uint8array'), await b.file(name)!.async('uint8array'))
})
test('deletion yields empty replacement and an identical neighbor survives a source-index-targeted save', async () => {
 const { parsed } = await open('<w:p><w:r><w:t>before</w:t></w:r></w:p>' + table + '<w:p/>' + table)
 const tables = parsed.blocks.filter(b => b.type === 'table'), block = tables[1]
 const result = lifecycle.editDocxTableLifecycle(block, operation(block), context(block)); assert.equal(result.replacementXml, '')
 const output = await saveDocx(parsed, parsed.blocks.filter(b => !b.hidden).map(b => b === block ? { kind: 'xml' as const, docxIndex: b.docxIndex!, xml: result.replacementXml } : { kind: 'original' as const, docxIndex: b.docxIndex! }))
 const read = await parseDocx(output); assert.equal(read.blocks.filter(b => b.type === 'table').length, 1); assert.equal(read.blocks.find(b => b.type === 'table')!.originalXml, tables[0].originalXml)
})
test('rejects forged refs, row bounds, unknown keys and protected documents independently', async () => {
 const { block } = await open(), ctx = context(block), op = operation(block, 1)
 for (const bad of [{ ...op, row: 0 }, { ...op, row: 3 }, { ...op, row: 1.5 }, { ...op, row: '1' }, { ...op, blockId: 'another-table' }, { ...op, expectedObjectSha256: 'x' }, { ...op, expectedObjectSha256: '0'.repeat(64) }, { ...op, clientXml: '<w:tbl/>' }, { ...operation(block), row: 1 }, [op], null]) assert.throws(() => lifecycle.editDocxTableLifecycle(block, bad as any, ctx))
 assert.throws(() => lifecycle.editDocxTableLifecycle(block, op, { ...ctx, expectedObjectSha256: '0'.repeat(64) }))
 assert.throws(() => lifecycle.editDocxTableLifecycle(block, op, { ...ctx, protectedDocument: true }))
 assert.equal(lifecycle.tableLifecycleAvailability(block, true).tableLifecycleEditable, false)
})
test('independent source validation refuses unsupported structures and forged model projections', async () => {
 for (const tag of ['<w:gridSpan w:val="2"/>', '<w:vMerge/>', '<w:sdt/>', '<w:commentReference w:id="1"/>', '<w:ins/>', '<w:tbl/>']) {
  const { block } = await open(table.replace('</w:tcPr>', tag + '</w:tcPr>'))
  assert.equal(lifecycle.tableLifecycleAvailability(block, false).tableLifecycleEditable, false)
  assert.throws(() => lifecycle.editDocxTableLifecycle(block, operation(block), context(block)))
 }
 const { block } = await open(); const forged = { ...block, table: { ...block.table!, rows: block.table!.rows.slice(0, 1) } }
 assert.equal(lifecycle.tableLifecycleAvailability(forged, false).tableLifecycleEditable, false)
 assert.throws(() => lifecycle.editDocxTableLifecycle(forged, operation(forged), context(forged)))
})

test('rejects namespace rebinding, unknown identity semantics and malformed source without trusting parsed fixtures', async () => {
 const { block } = await open()
 for (const originalXml of [
  block.originalXml!.replace('w:rsidR="11223344"', 'w:rsidR="11223344" w:custom="opaque"'),
  block.originalXml!.replace('w:rsidR="11223344"', 'w:rsidR="not-a-rsid"'),
  block.originalXml!.replace('w:rsidR="11223344"', 'xmlns:w="urn:foreign"'),
  block.originalXml!.replace('<w:p ', '<w:p xmlns:w="urn:foreign" '),
  block.originalXml!.replace('</w:tbl>', '</w:wrong>'),
  block.originalXml!.replace('<w:tblGrid>', '<!-- opaque --><w:tblGrid>'),
 ]) {
  const unsafe = { ...block, originalXml }
  assert.equal(lifecycle.tableLifecycleAvailability(unsafe, false).tableLifecycleEditable, false)
  assert.throws(() => lifecycle.editDocxTableLifecycle(unsafe, operation(unsafe), context(unsafe)))
 }
 for (const wrapped of [{ ...block, sdtShell: {} }, { ...block, sdtShells: [{}] }, { ...block, blockRevision: { kind: 'ins' } }]) {
  assert.equal(lifecycle.tableLifecycleAvailability(wrapped as any, false).tableLifecycleEditable, false)
  assert.throws(() => lifecycle.editDocxTableLifecycle(wrapped as any, operation(block), context(block)))
 }
})
test('split accepts every interior cut and plain tables; deletion accepts a single-row source', async () => {
 for (const row of [1, 2]) {
  const { block } = await open(generated), result = lifecycle.editDocxTableLifecycle(block, operation(block, row), context(block))
  const read = await open(result.replacementXml)
  assert.deepEqual(read.parsed.blocks.filter(b => b.table).map(b => b.table!.rows.length), [row, 3 - row])
 }
 const { block } = await open(generateTableModelXml({ ...model, rows: model.rows.slice(0, 1) }))
 assert.equal(lifecycle.editDocxTableLifecycle(block, operation(block), context(block)).replacementXml, '')
 assert.throws(() => lifecycle.editDocxTableLifecycle(block, operation(block, 1), context(block)))
})

test('ordinary auto and percentage table widths and absent layout remain source-preserved lifecycle targets', async () => {
 const sourceWidth = /<w:tblW\b[^>]*\/>/.exec(generated)![0]
 const sourceLayout = /<w:tblLayout\b[^>]*\/>/.exec(generated)![0]
 for (const width of ['<w:tblW w:type="auto" w:w="0"/>', '<w:tblW w:type="pct" w:w="5000"/>', '']) {
  for (const layout of ['', '<w:tblLayout w:type="autofit"/>']) {
   const source = generated.replace(sourceWidth, width).replace(sourceLayout, layout)
   const { block } = await open(source)
   assert.equal(lifecycle.tableLifecycleAvailability(block, false).tableLifecycleEditable, true)
   assert.equal(lifecycle.editDocxTableLifecycle(block, operation(block), context(block)).replacementXml, '')
   const result = lifecycle.editDocxTableLifecycle(block, operation(block, 1), context(block))
   const read = await open(result.replacementXml)
   const tables = read.parsed.blocks.filter(b => b.type === 'table')
   assert.equal(tables.length, 2)
   for (const value of tables) {
    if (width) assert.ok(value.originalXml!.includes(width))
    else assert.equal(/<w:tblW\b/.test(value.originalXml!), false)
    if (layout) assert.ok(value.originalXml!.includes(layout))
    else assert.equal(/<w:tblLayout\b/.test(value.originalXml!), false)
   }
  }
 }
})
test('lifecycle width projection refuses unknown width and layout attributes and kinds', async () => {
 for (const [target, bad] of [
  [/ w:type="dxa"(?=\/?>)/, ' w:type="unknown"'],
  [/<w:tblW\b[^>]*\/>/, '<w:tblW w:w="0" w:type="auto" w:opaque="1"/>'],
  [/<w:tblW\b[^>]*\/>/, '<w:tblW w:w="5" w:type="auto"/>'],
  [/<w:tblLayout\b[^>]*\/>/, '<w:tblLayout w:type="autofit" w:opaque="1"/>'],
  [/<w:tblLayout\b[^>]*\/>/, '<w:tblLayout w:type="unknown"/>'],
 ] as const) {
  const { block } = await open(generated.replace(target, bad))
  assert.equal(lifecycle.tableLifecycleAvailability(block, false).tableLifecycleEditable, false)
  assert.throws(() => lifecycle.editDocxTableLifecycle(block, operation(block), context(block)))
 }
})
