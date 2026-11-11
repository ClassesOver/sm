import { expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { TableMap } from '@tiptap/pm/tables'
import { applyTableColumnWidthSteps } from './docx-table-column-width-core'
const attrs = (a: Record<string, unknown>) => Object.fromEntries(Object.entries(a).map(([k, v]) => [k, { default: v }]))
const schema = new Schema({ nodes: {
  doc: { content: 'docTable+' }, text: { group: 'inline' },
  docParagraph: { content: 'text*', attrs: attrs({ docxIndex: null, keepNext: false }) },
  docTable: { content: 'docTableRow+', tableRole: 'table', attrs: attrs({ colWidthsPct: null }) },
  docTableRow: { content: 'docTableCell*', tableRole: 'row', attrs: attrs({ rawTrPr: null, heightTwips: null, cantSplitEdited: false }) },
  docTableCell: { content: 'docParagraph+', tableRole: 'cell', attrs: attrs({ colspan: 1, rowspan: 1, colwidth: null, rawTcPr: null }) },
}, marks: { bold: {} } })
function fixture() {
  return schema.node('docTable', null, ['A', 'B'].map(r => schema.node('docTableRow', { rawTrPr: r, heightTwips: 100 }, [0, 1].map(c => schema.node('docTableCell', { rawTcPr: `${r}${c}` }, schema.node('docParagraph', { docxIndex: `${r}${c}`, keepNext: true }, schema.text(`${r}${c}`, [schema.mark('bold')])))))))
}
it('preserves odd unselected twips and projects widths without changing content', () => {
  const before = fixture(), result = applyTableColumnWidthSteps(before, [2401, 3001], 9000, [{ kind: 'setTableColumnWidth', left: 0, right: 1, widthTwips: 3000 }])
  expect(result.widthsTwips).toEqual([3000, 3001])
  expect(result.table.lastChild!.firstChild!.firstChild!.toJSON()).toEqual(before.lastChild!.firstChild!.firstChild!.toJSON())
  expect(result.table.lastChild!.lastChild!.attrs.colwidth).toEqual([3001 / 15])
})
it('distributes odd totals deterministically, uses whole table for a single-column selection', () => {
  const result = applyTableColumnWidthSteps(fixture(), [2401, 3000], 9000, [{ kind: 'distributeTableColumns', left: 1, right: 2 }])
  expect(result.widthsTwips).toEqual([2701, 2700])
})
it('reuses source fit priorities and rejects unsafe inputs', () => {
  expect(applyTableColumnWidthSteps(fixture(), [3000, 3000], 7500, [{ kind: 'setTableColumnWidth', left: 0, right: 1, widthTwips: 6750 }]).widthsTwips).toEqual([6750, 750])
  for (const steps of [[], Array(51).fill({ kind: 'distributeTableColumns', left: 0, right: 2 }), [{ kind: 'setTableColumnWidth', left: 0, right: 1, widthTwips: 0 }], [{ kind: 'distributeTableColumns', left: 0, right: 3 }], [{ kind: 'distributeTableColumns', left: 0, right: 2, extra: 1 }]]) expect(() => applyTableColumnWidthSteps(fixture(), [2401, 3000], 9000, steps as any)).toThrow()
})
it('supports merged slots, repeats distribution without drift and preserves paragraphs', () => {
  const plain = fixture(), cell = plain.firstChild!.firstChild!
  const merged = plain.type.create(null, [plain.firstChild!.type.create(null, [cell.type.create({ ...cell.attrs, colspan: 2, rowspan: 2 }, cell.content)]), plain.lastChild!.type.create()])
  const result = applyTableColumnWidthSteps(merged, [2401, 3000], 9000, Array.from({ length: 50 }, () => ({ kind: 'distributeTableColumns' as const, left: 0, right: 2 })))
  expect(result.widthsTwips).toEqual([2701, 2700])
  expect(result.table.firstChild!.firstChild!.attrs.colwidth).toEqual([2701 / 15, 180])
  expect(result.table.firstChild!.firstChild!.content.eq(cell.content)).toBe(true)
})
it('matches source three-column fit and keeps unselected odd columns over repeated requests', () => {
  const plain = fixture(), row = plain.firstChild!, table = plain.type.create(null, [row.type.create(null, [row.firstChild!, row.firstChild!, row.firstChild!])])
  expect(applyTableColumnWidthSteps(table, [3000, 3000, 3000], 9000, [{ kind: 'setTableColumnWidth', left: 0, right: 1, widthTwips: 7500 }]).widthsTwips).toEqual([7500, 750, 750])
  const repeated = applyTableColumnWidthSteps(fixture(), [2401, 3001], 9000, Array.from({ length: 50 }, () => ({ kind: 'setTableColumnWidth' as const, left: 0, right: 1, widthTwips: 3000 })))
  expect(repeated.widthsTwips).toEqual([3000, 3001])
})
it.each([15, 30])('keeps %s-column odd totals exactly stable through repeated distribution', n => {
  const plain = fixture(), row = plain.firstChild!, make = () => plain.type.create(null, [row.type.create(null, Array.from({ length: n }, () => row.firstChild!))])
  const widths = Array.from({ length: n }, (_, c) => 601 + c), total = widths.reduce((a, b) => a + b, 0)
  const result = applyTableColumnWidthSteps(make(), widths, 30000, Array.from({ length: 50 }, () => ({ kind: 'distributeTableColumns' as const, left: 0, right: n })))
  expect(result.widthsTwips.reduce((a, b) => a + b, 0)).toBe(total)
  const partial = applyTableColumnWidthSteps(make(), widths, 30000, [{ kind: 'distributeTableColumns', left: 1, right: n - 1 }])
  expect(partial.widthsTwips[0]).toBe(widths[0]); expect(partial.widthsTwips[n - 1]).toBe(widths[n - 1])
  expect(partial.widthsTwips.reduce((a, b) => a + b, 0)).toBe(total)
})
