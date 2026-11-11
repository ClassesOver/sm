import assert from 'node:assert/strict'
import { test } from 'node:test'
import { patchNestedCellText, type NestedTarget } from '../docx-nested-tables.ts'

const paragraph = (value: string) => `<w:p><w:r><w:t>${value}</w:t></w:r></w:p>`
const leaf = `<w:tc>${paragraph('a')}${paragraph('b')}</w:tc>`
const xml = `<w:tbl><w:tr><w:tc>${paragraph('before')}<w:tbl><w:tr>${leaf}</w:tr></w:tbl>${paragraph('after')}</w:tc></w:tr></w:tbl>`
const target: NestedTarget = { tableId: 'table', row: 0, column: 0, nestedOrdinal: 0, nestedRow: 0, nestedColumn: 0,
  anchor: { cellId: 'cell', expectedObjectSha256: 'hash', editable: true, paragraphs: ['a', 'b'] } }

test('补丁静默no-op必须被完整数组回读拒绝', () => {
  assert.throws(() => patchNestedCellText(xml, target, ['changed'], source => source), /nested_write_not_applied/)
  // ['a','b']与['a\nb']的join相同，但数组语义不同。
  assert.throws(() => patchNestedCellText(xml, target, ['a\nb'], source => source), /nested_write_not_applied/)
})
test('未变化段落逐字保留，增删段落按完整数组执行', () => {
  const patched = patchNestedCellText(xml, target, ['a', 'changed', ''])
  assert.ok(patched.includes(paragraph('a')))
  assert.ok(patched.includes('<w:p></w:p>'))
  assert.equal(patchNestedCellText(patched, target, ['a']), xml.replace(leaf, `<w:tc>${paragraph('a')}</w:tc>`))
})
test('目标外字节变化必须拒绝', () => {
  assert.throws(() => patchNestedCellText(xml, target, ['a', 'b'], source => source.replace('before', 'tampered')), /nested_write_not_applied/)
})
