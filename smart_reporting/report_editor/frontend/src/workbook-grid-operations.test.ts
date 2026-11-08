import { expect, it } from 'vitest'
import { parseRange } from '@sheets-web/xlsx-engine'
import { gridMergeChanges, planGridSheets, structuralMutation } from './workbook-grid-operations'

function mergeChanges(before: string[], after: string[]) {
  return gridMergeChanges(
    { sheets: [{ name: '汇总', merges: before }] },
    { sheets: [{ name: '汇总', cells: {}, merges: after.map(parseRange) }] },
  )
}

it('captures new merges and removing the last merge from the final grid snapshot', () => {
  expect(mergeChanges([], ['A1:B2'])).toEqual([{ sheetName: '汇总', ranges: ['A1:B2'] }])
  expect(mergeChanges(['A1:B2'], [])).toEqual([{ sheetName: '汇总', ranges: [] }])
})

it('ignores merge ordering and supports restoring the imported layout through undo', () => {
  expect(mergeChanges(['A1:B2', 'D1:E2'], ['D1:E2', 'A1:B2'])).toEqual([])
  expect(mergeChanges(['A1:B2'], ['A1:B2'])).toEqual([])
})

it('preserves renamed, added, removed and reordered tabs in original engine protocol', () => {
  const result = planGridSheets(['汇总', '旧明细'], { sheetOrder: ['new-id', 'sheet-0'], sheets: { 'sheet-0': { name: '摘要' }, 'new-id': { name: '新明细' } } })
  expect(result).toEqual({ renames: [{ sheetName: '汇总', newName: '摘要' }], additions: [{ name: '新明细' }], removals: ['旧明细'], order: ['新明细', '摘要'] })
})

it('converts grid row-column mutation coordinates without changing one-based semantics', () => {
  expect(structuralMutation('sheet.mutation.insert-row', { subUnitId: 'sheet-0', range: { startRow: 3, endRow: 4 } })).toEqual({ sheetId: 'sheet-0', op: { kind: 'insert-rows', index: 3, count: 2 } })
  expect(structuralMutation('sheet.mutation.remove-rows', { subUnitId: 'sheet-0', range: { startRow: 3, endRow: 4 } })).toEqual({ sheetId: 'sheet-0', op: { kind: 'remove-rows', index: 3, count: 2 } })
  expect(structuralMutation('sheet.mutation.remove-col', { subUnitId: 'sheet-0', range: { startColumn: 2, endColumn: 2 } })).toEqual({ sheetId: 'sheet-0', op: { kind: 'remove-cols', index: 2, count: 1 } })
})
