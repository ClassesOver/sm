import { expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { TableMap } from '@tiptap/pm/tables'
import { applyTableRowHeightSteps } from './docx-table-row-height-core'
const attrs = (a: Record<string, unknown>) => Object.fromEntries(Object.entries(a).map(([k, v]) => [k, { default: v }]))
const schema = new Schema({ nodes: {
  doc: { content: 'docTable+' }, text: { group: 'inline' },
  docParagraph: { content: 'text*', attrs: attrs({ docxIndex: null, keepNext: false }) },
  docTable: { content: 'docTableRow+', tableRole: 'table', attrs: attrs({ colWidthsPct: null }) },
  docTableRow: { content: 'docTableCell*', tableRole: 'row', attrs: attrs({ rawTrPr: null, heightTwips: null, heightRule: null, cantSplitEdited: false }) },
  docTableCell: { content: 'docParagraph+', tableRole: 'cell', attrs: attrs({ colspan: 1, rowspan: 1, colwidth: null, rawTcPr: null }) },
}, marks: { bold: {} } })
function fixture() {
  return schema.node('docTable', null, ['A', 'B'].map(r => schema.node('docTableRow', { rawTrPr: r, heightTwips: 100, heightRule: r === 'A' ? 'exact' : 'atLeast' }, [0, 1].map(c => schema.node('docTableCell', { rawTcPr: `${r}${c}` }, schema.node('docParagraph', { docxIndex: `${r}${c}`, keepNext: true }, schema.text(`${r}${c}`, [schema.mark('bold')])))))))
}
it('sets selected heights with original rules, clamps max and preserves cells/other attrs', () => {
  const original = fixture(), result = applyTableRowHeightSteps(original, 1000, [{ top: 0, bottom: 2, heightTwips: 2000 }])
  expect(result.rowHeightsTwips).toEqual([1000, 1000]); expect(result.rowHeightRules).toEqual(['exact', 'atLeast'])
  expect(result.table.firstChild!.attrs.rawTrPr).toBe('A')
  expect(result.table.firstChild!.content.eq(original.firstChild!.content)).toBe(true)
})
it('clears only selected heights and supports multiple current-row steps on merged sources', () => {
  const plain = fixture(), cell = plain.firstChild!.firstChild!
  const merged = plain.type.create(null, [plain.firstChild!.type.create(plain.firstChild!.attrs, [cell.type.create({ ...cell.attrs, colspan: 2, rowspan: 2 }, cell.content)]), plain.lastChild!.type.create(plain.lastChild!.attrs)])
  const result = applyTableRowHeightSteps(merged, 1000, [{ top: 0, bottom: 2, heightTwips: 600 }, { top: 1, bottom: 2, heightTwips: null }])
  expect(result.rowHeightsTwips).toEqual([600, null]); expect(result.rowHeightRules).toEqual(['exact', null])
  expect(result.table.firstChild!.firstChild!.attrs).toEqual(merged.firstChild!.firstChild!.attrs)
})
it('rejects unknown fields, invalid row bands/heights/budgets without changing input', () => {
  const original = fixture(), before = original.toJSON()
  for (const steps of [[], Array(51).fill({ top: 0, bottom: 1, heightTwips: 1 }), [{ top: 0, bottom: 3, heightTwips: 1 }], [{ top: 0, bottom: 1, heightTwips: 0 }], [{ top: 0, bottom: 1, heightTwips: 1.5 }], [{ top: 0, bottom: 1, heightTwips: null, rule: 'exact' }]]) expect(() => applyTableRowHeightSteps(original, 1000, steps as any)).toThrow()
  expect(original.toJSON()).toEqual(before)
})
it('distribute forces atLeast, preserves measured height above section max and replays mixed steps without reviving exact', () => {
  const table = fixture()
  for (const clear of [false, true]) {
    const result = applyTableRowHeightSteps(table, 1000, [{ top: 0, bottom: 2, heightTwips: 400 }, { kind: 'distributeTableRows', top: 0, bottom: 1, heightTwips: 2000 }, ...(clear ? [{ top: 0, bottom: 1, heightTwips: null }] : []), { top: 0, bottom: 1, heightTwips: 500 }])
    expect(result.rowHeightsTwips).toEqual([500, 400]); expect(result.rowHeightRules).toEqual(['atLeast', 'atLeast'])
    expect(result.table.firstChild!.content.eq(table.firstChild!.content)).toBe(true)
  }
  expect(applyTableRowHeightSteps(table, 1000, [{ kind: 'distributeTableRows', top: 0, bottom: 1, heightTwips: 2000 }]).rowHeightsTwips).toEqual([2000, 100])
})
it('distribute rejects malformed steps, client rules and nullable heights', () => {
  for (const extra of [{ kind: 'distributeTableRows', heightTwips: 31681 }, { kind: 'unknown', heightTwips: 500 }, { kind: 'distributeTableRows', heightTwips: null }, { kind: 'distributeTableRows', heightTwips: 0 }, { kind: 'distributeTableRows', heightTwips: 1.5 }, { kind: 'distributeTableRows', heightTwips: Number.MAX_SAFE_INTEGER + 1 }, { kind: 'distributeTableRows', heightTwips: 500, heightRule: 'exact' }]) expect(() => applyTableRowHeightSteps(fixture(), 1000, [{ top: 0, bottom: 1, ...extra }] as any)).toThrow()
})
