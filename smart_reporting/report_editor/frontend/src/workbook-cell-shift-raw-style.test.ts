import { expect, it } from 'vitest'
const implementation = './workbook-cell-shift-raw-style'
const range = { startRow: 1, endRow: 1, startColumn: 0, endColumn: 0 }
const outer = (id = 'insert-range-move-down') => ({ id: `sheet.command.${id}`, params: { range } })
const nested = (cell: any = { s: { bg: { rgb: '#FFFF00' } } }) => ({ id: 'sheet.command.set-range-values', params: { unitId: 'u', subUnitId: 's', range, cellValue: { 1: { 0: cell } } } })
const workbook = (style?: any) => ({ getId: () => 'u', getActiveSheet: () => ({ getSheetId: () => 's', getSelection: () => ({ getActiveRange: () => ({ getRange: () => range }) }), getSheet: () => ({ getCellRaw: () => ({ v: 2, ...(style === undefined ? {} : { s: style }) }) }) }) })

it('strips only the automatic inserted-cell projected style and consumes its exact command scope once', async () => {
  const { createCellShiftRawStyleGuard } = await import(/* @vite-ignore */ implementation)
  const guard = createCellShiftRawStyleGuard(), automatic = nested()
  guard.begin(outer(), workbook())
  guard.normalize(automatic)
  expect(automatic.params.cellValue[1][0]).toBeNull()
  const userEdit = nested(); guard.normalize(userEdit)
  expect(userEdit.params.cellValue[1][0]).toEqual({ s: { bg: { rgb: '#FFFF00' } } })
})

it.each(['insert-range-move-down', 'insert-range-move-right'])('preserves genuine raw style during %s', async id => {
  const { createCellShiftRawStyleGuard } = await import(/* @vite-ignore */ implementation)
  const style = { bg: { rgb: '#0000FF' }, bl: 1 }, guard = createCellShiftRawStyleGuard(), automatic = nested()
  guard.begin(outer(id), workbook(style)); guard.normalize(automatic)
  expect(automatic.params.cellValue[1][0]).toEqual({ s: style })
  expect(automatic.params.cellValue[1][0].s).not.toBe(style)
})

it('leaves ordinary values, foreign sheets and mismatched ranges untouched', async () => {
  const { createCellShiftRawStyleGuard } = await import(/* @vite-ignore */ implementation)
  const guard = createCellShiftRawStyleGuard(); guard.begin(outer(), workbook())
  const value = nested({ v: 3, s: { bg: { rgb: '#123456' } } }), foreign = nested(), otherRange = nested()
  foreign.params.subUnitId = 'other'; otherRange.params.range = { ...range, endRow: 2 }
  const originals = structuredClone([value, foreign, otherRange])
  for (const command of [value, foreign, otherRange]) guard.normalize(command)
  expect([value, foreign, otherRange]).toEqual(originals)
  const actual = nested(); guard.normalize(actual); expect(actual.params.cellValue[1][0]).toBeNull()
})

it('expires canceled/failed command scopes before later user edits and clears on completion', async () => {
  const { createCellShiftRawStyleGuard } = await import(/* @vite-ignore */ implementation)
  const guard = createCellShiftRawStyleGuard(), command = outer()
  guard.begin(command, workbook()); await Promise.resolve()
  const expired = nested(), before = structuredClone(expired); guard.normalize(expired); expect(expired).toEqual(before)
  guard.begin(command, workbook()); guard.clear(command)
  const completed = nested(); guard.normalize(completed); expect(completed).toEqual(before)
})

it.each(['delete-range-move-up', 'delete-range-move-left', 'set-range-values'])('does not normalize styles for %s', async id => {
  const { createCellShiftRawStyleGuard } = await import(/* @vite-ignore */ implementation)
  const guard = createCellShiftRawStyleGuard(), command = nested(), before = structuredClone(command)
  guard.begin(outer(id), workbook()); guard.normalize(command); expect(command).toEqual(before)
})

it('captures the current selection when the native insert command has no params', async () => {
  const { createCellShiftRawStyleGuard } = await import(/* @vite-ignore */ implementation)
  const guard = createCellShiftRawStyleGuard(), command = nested()
  guard.begin({ id: 'sheet.command.insert-range-move-down' }, workbook())
  guard.normalize(command); expect(command.params.cellValue[1][0]).toBeNull()
})
