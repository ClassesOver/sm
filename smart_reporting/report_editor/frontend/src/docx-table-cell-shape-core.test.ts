import { expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { TableMap } from '@tiptap/pm/tables'
import { applyTableCellShapeSteps, type TableCellShapeStep } from './docx-table-cell-shape-core'
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
const rect = { top: 0, left: 0, bottom: 2, right: 2 }
const merge: TableCellShapeStep = { kind: 'mergeTableCells', rect }
const split = (r = rect, rows = 1, columns = 2, mergeFirst = true): TableCellShapeStep => ({ kind: 'splitTableCells', rect: r, rows, columns, mergeFirst })
it('merges in row order preserving attrs/marks, then default splits merged cells', () => {
  const merged = applyTableCellShapeSteps(fixture(), [2401, 3000], [merge])
  expect(TableMap.get(merged.table).map.every(p => p === 1)).toBe(true)
  const paras = merged.table.firstChild!.firstChild!
  expect(Array.from({ length: paras.childCount }, (_, i) => paras.child(i).attrs.docxIndex)).toEqual(['A0', 'A1', 'B0', 'B1'])
  expect(paras.child(2).firstChild!.marks[0].type.name).toBe('bold')
  const result = applyTableCellShapeSteps(merged.table, merged.widthsTwips, [split()])
  expect(result.table.firstChild!.childCount).toBe(2)
  expect(result.table.firstChild!.firstChild!.attrs.rowspan).toBe(2)
  expect(result.table.firstChild!.child(1).firstChild!.attrs).toMatchObject({ docxIndex: null, keepNext: true })
  expect(result.table.firstChild!.firstChild!.childCount).toBe(4)
})
it('expands rows/columns with neighbour spans and integer odd-width projection', () => {
  const result = applyTableCellShapeSteps(fixture(), [2401, 3000], [split({ top: 0, left: 0, bottom: 1, right: 1 }, 3, 2)])
  expect(result.widthsTwips).toEqual([1201, 1200, 3000])
  const map = TableMap.get(result.table)
  expect([map.width, map.height]).toEqual([3, 4])
  expect(result.table.firstChild!.lastChild!.attrs.rowspan).toBe(3)
  expect(result.table.lastChild!.firstChild!.attrs.colspan).toBe(2)
  expect(result.table.child(1).attrs).toMatchObject({ rawTrPr: null, heightTwips: null, cantSplitEdited: true })
  expect(result.table.firstChild!.firstChild!.attrs.colwidth).toEqual([1201 / 15])
})
it('splits each selected cell right to left and chains current coordinates', () => {
  const result = applyTableCellShapeSteps(fixture(), [2401, 3001], [split({ top: 0, left: 0, bottom: 1, right: 2 }, 1, 2, false)])
  expect(result.widthsTwips).toEqual([1201, 1200, 1501, 1500])
  expect(Array.from({ length: 4 }, (_, i) => result.table.firstChild!.child(i).textContent)).toEqual(['A0', '', 'A1', ''])
  const chained = applyTableCellShapeSteps(fixture(), [2401, 3000], [merge, split(rect, 2, 2), { kind: 'mergeTableCells', rect: { top: 0, left: 0, bottom: 1, right: 2 } }])
  expect(chained.table.firstChild!.firstChild!.attrs).toMatchObject({ colspan: 2, rowspan: 1 })
})
it('rejects unsafe payloads, span cuts and budgets', () => {
  for (const steps of [[{ ...merge, extra: 1 }], [split(rect, 1, 1)], [split(rect, 1.5, 2)], [{ ...merge, rect: { ...rect, right: 3 } }], Array(51).fill(merge)]) expect(() => applyTableCellShapeSteps(fixture(), [2401, 3000], steps as TableCellShapeStep[])).toThrow()
  const merged = applyTableCellShapeSteps(fixture(), [2401, 3000], [merge]).table
  expect(() => applyTableCellShapeSteps(merged, [2401, 3000], [split({ ...rect, bottom: 1 })])).toThrow()
  expect(() => applyTableCellShapeSteps(fixture(), [1, 3000], [split({ top: 0, left: 0, bottom: 1, right: 1 })])).toThrow()
  expect(() => applyTableCellShapeSteps(fixture(), [2401, 3000], [split(rect, 50, 30)])).toThrow()
})
it.each([
  { top: 0, left: 0, bottom: 1, right: 2 },
  { top: 0, left: 0, bottom: 2, right: 1 },
])('supports horizontal and vertical merges %#', rect => {
  const result = applyTableCellShapeSteps(fixture(), [2401, 3000], [{ kind: 'mergeTableCells', rect }])
  expect(result.table.firstChild!.firstChild!.attrs).toMatchObject({ colspan: rect.right, rowspan: rect.bottom, rawTcPr: 'A0' })
  expect(result.widthsTwips).toEqual([2401, 3000])
})
it('retains source span partitions when a split requests fewer pieces than existing span', () => {
  const merged = applyTableCellShapeSteps(fixture(), [2401, 3000], [merge])
  const result = applyTableCellShapeSteps(merged.table, merged.widthsTwips, [split(rect, 2, 1)])
  expect(result.table.firstChild!.firstChild!.attrs).toMatchObject({ colspan: 2, rowspan: 1 })
  expect(result.table.lastChild!.firstChild!.attrs).toMatchObject({ colspan: 2, rowspan: 1 })
  expect(result.table.lastChild!.firstChild!.firstChild!.attrs.docxIndex).toBeNull()
  expect(result.table.attrs.colWidthsPct.reduce((a: number, b: number) => a + b, 0)).toBeCloseTo(100)
})
it('matches PM formatted-empty paragraph skipping and leaves input untouched on later failure', () => {
  const table = fixture(), json = table.toJSON()
  json.content![0].content![1].content![0].content = []
  const withEmpty = schema.nodeFromJSON(json), before = withEmpty.toJSON()
  const result = applyTableCellShapeSteps(withEmpty, [2401, 3000], [merge])
  expect(result.table.firstChild!.firstChild!.childCount).toBe(3)
  expect(() => applyTableCellShapeSteps(withEmpty, [2401, 3000], [merge, split({ ...rect, right: 1 })])).toThrow()
  expect(withEmpty.toJSON()).toEqual(before)
  const oversized = table.type.create(table.attrs, [table.firstChild!.type.create(null, [table.firstChild!.firstChild!.type.create({ colspan: 1e9 }, table.firstChild!.firstChild!.content)])])
  expect(() => applyTableCellShapeSteps(oversized, [2401], [merge])).toThrow()
})
it('rejects a schema requiring physical cells on fully covered rows', () => {
  const nodes = schema.spec.nodes.update('docTableRow', { ...schema.spec.nodes.get('docTableRow')!, content: 'docTableCell+' })
  const strict = new Schema({ nodes, marks: schema.spec.marks })
  expect(() => applyTableCellShapeSteps(strict.nodeFromJSON(fixture().toJSON()), [2401, 3000], [merge])).toThrow()
})
