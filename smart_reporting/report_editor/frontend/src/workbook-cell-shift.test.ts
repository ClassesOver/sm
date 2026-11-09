import { expect, it } from 'vitest'
import { CELL_SHIFT_COMMANDS, cellShiftRange, cellsCommandId, cellsCommandParams, decideCellsAction } from './workbook-cell-shift'

const range = (startRow: number, endRow: number, startColumn: number, endColumn: number, rangeType = 0) => ({ startRow, endRow, startColumn, endColumn, rangeType })

it('acts directly on whole rows/columns and asks otherwise (fixed-source decideCellsAction)', () => {
  expect(decideCellsAction({ range: range(1, 2, 0, 0, 1), rowCount: 100, columnCount: 20 })).toEqual({ kind: 'direct', choice: 'entire-row' })
  expect(decideCellsAction({ range: range(1, 1, 0, 19), rowCount: 100, columnCount: 20 })).toEqual({ kind: 'direct', choice: 'entire-row' })
  expect(decideCellsAction({ range: range(0, 99, 3, 3), rowCount: 100, columnCount: 20 })).toEqual({ kind: 'direct', choice: 'entire-column' })
  expect(decideCellsAction({ range: range(1, 2, 1, 2), rowCount: 100, columnCount: 20 })).toEqual({ kind: 'dialog' })
})

it('maps every choice to the official command, passes the captured range to shifts and journals the engine direction', () => {
  expect(cellsCommandId('insert', 'shift-horizontal')).toBe('sheet.command.insert-range-move-right')
  expect(cellsCommandId('delete', 'shift-vertical')).toBe('sheet.command.delete-range-move-up')
  expect(cellsCommandId('insert', 'entire-row')).toBe('sheet.command.insert-row-before')
  expect(cellsCommandId('delete', 'entire-column')).toBe('sheet.command.remove-col')
  expect(cellsCommandParams('insert', 'entire-row', range(2, 4, 0, 0))).toEqual({ value: 3 })
  expect(cellsCommandParams('delete', 'entire-row', range(2, 4, 0, 0))).toBeUndefined()
  expect(cellsCommandParams('delete', 'shift-horizontal', range(1, 2, 1, 3, 0))).toEqual({ range: { startRow: 1, endRow: 2, startColumn: 1, endColumn: 3 } })
  expect(Object.values(CELL_SHIFT_COMMANDS)).toEqual(['right', 'down', 'left', 'up'])
  expect(cellShiftRange(range(1, 2, 1, 3))).toBe('B2:D3')
  expect(cellShiftRange(range(0, 0, 0, 0))).toBe('A1')
})
