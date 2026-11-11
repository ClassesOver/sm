import { expect, it } from 'vitest'
import { applyPageSetups, applyRowColumnOps, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { shiftPageBreakIndexes, shiftSpecOf } from '@sheets-web/xlsx-engine/structural'
const sheet = async (bytes: Uint8Array) => (await readWorkbook(bytes)).sheets[0]!
it('moves persisted row and column breaks with inserts and removes deleted boundaries', async () => {
  const source = await applyPageSetups(await createBlankWorkbook(), [{ sheetName: 'Sheet1', rowBreaks: [3, 10], colBreaks: [2, 6], printArea: 'A1:H20' }])
  for (const [op, rows, columns] of [
    [{ kind: 'insert-rows', index: 2, count: 3 }, [6, 13], [2, 6]],
    [{ kind: 'remove-rows', index: 2, count: 3 }, [7], [2, 6]],
    [{ kind: 'insert-cols', index: 1, count: 2 }, [3, 10], [4, 8]],
    [{ kind: 'remove-cols', index: 1, count: 2 }, [3, 10], [4]],
  ] as const) {
    const after = await sheet(await applyRowColumnOps(source, 'Sheet1', [op]))
    expect(after.rowBreaks).toEqual(rows); expect(after.colBreaks).toEqual(columns)
  }
})
it('exposes the same index transform for journal epochs and persisted XML', () => {
  expect(shiftPageBreakIndexes([3, 10], shiftSpecOf({ kind: 'insert-rows', index: 2, count: 3 }))).toEqual([6, 13])
  expect(shiftPageBreakIndexes([2, 3], shiftSpecOf({ kind: 'remove-rows', index: 0, count: 3 }))).toEqual([])
})
it('preserves other-axis XML and break metadata while maintaining counts after deletion', async () => {
  const { applyStructuralOp } = await import('@sheets-web/xlsx-engine/structural')
  const xml = '<worksheet><sheetData></sheetData><rowBreaks count="2" manualBreakCount="1"><brk id="3" min="0" max="16383" man="1"/><brk id="10" min="2" max="8" man="0"/></rowBreaks><colBreaks count="1" manualBreakCount="1"><brk id="4" min="0" max="99" man="1"/></colBreaks></worksheet>'
  const after = applyStructuralOp(xml, { kind: 'remove-rows', index: 2, count: 3 }, 'Data')
  expect(after).toContain('<rowBreaks count="1" manualBreakCount="0"><brk id="7" min="2" max="8" man="0"/></rowBreaks>')
  expect(after).toContain('<colBreaks count="1" manualBreakCount="1"><brk id="4" min="0" max="99" man="1"/></colBreaks>')
})
