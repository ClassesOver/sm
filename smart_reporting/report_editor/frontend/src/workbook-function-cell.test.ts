import { describe, expect, it, vi } from 'vitest'
import { Univer, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin, IFunctionService } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'

import { CellWithFilename, installCellFilenameFunction } from './workbook-function-cell'
import { BaseFunction, ErrorValueObject, StringValueObject } from '@univerjs/engine-formula'
it('resolves saved-file CELL filename through real formulas, including referenced sheet and nested sheet-name idiom', async () => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  let installed: { dispose(): void } | undefined
  try {
    const api = FUniver.newAPI(univer)
    const book = api.createWorkbook({ id: 'cell-file', name: 'File', sheetOrder: ['one', 'two'], sheets: {
      one: { id: 'one', name: 'One', rowCount: 20, columnCount: 10 },
      two: { id: 'two', name: 'Other Sheet', rowCount: 20, columnCount: 10 },
    } })
    const service = univer.__getInjector().get(IFunctionService)
    const original = service.getExecutor('CELL')
    installed = installCellFilenameFunction({ univer }, () => '/reports/source.xlsx')
    const sheet = book.getActiveSheet()!
    sheet.getRange('A1:D1').setValues([[{ f: '=CELL("filename")' }, { f: '=CELL("filename",\'Other Sheet\'!B1)' },
      { f: '=MID(CELL("filename",B1),FIND("]",CELL("filename",B1))+1,31)' }, { f: '=CELL("row",B3)' }]])
    await vi.waitFor(() => {
      expect(sheet.getRange('A1').getValue()).toBe('/reports/[source.xlsx]One')
      expect(sheet.getRange('B1').getValue()).toBe('/reports/[source.xlsx]Other Sheet')
      expect(sheet.getRange('C1').getValue()).toBe('One')
      expect(sheet.getRange('D1').getValue()).toBe(3)
    }, { timeout: 3000 })
    installed!.dispose()
    expect(service.getExecutor('CELL')).toBe(original)
  } finally { installed?.dispose(); univer.dispose() }
}, 10000)

function infoType(value: string) {
  return StringValueObject.create(value)
}

function refOn(sheetId: string | undefined, defaultSheetId?: string) {
  return {
    isError: () => false,
    isReferenceObject: () => true,
    getForcedSheetId: () => sheetId,
    getDefaultSheetId: () => defaultSheetId,
  }
}

function makeCell(path: string | null, original?: BaseFunction) {
  const cell = new CellWithFilename('CELL', original, () => path)
  cell.setRefInfo('unit1', 'sheet-a', 3, 2)
  cell.setSheetsInfo({
    sheetOrder: ['sheet-a', 'sheet-b'],
    sheetNameMap: { 'sheet-a': 'COUNT Functions', 'sheet-b': 'Sheet 2' },
  } as never)
  return cell
}

describe('CELL("filename")', () => {
  it('returns dir/[book]sheet for the referenced sheet', () => {
    const result = makeCell('/Users/x/Downloads/Workshop v1.xlsx').calculate(
      infoType('filename'),
      refOn(undefined, 'sheet-a') as never,
    ) as StringValueObject
    expect(result.getValue()).toBe('/Users/x/Downloads/[Workshop v1.xlsx]COUNT Functions')
  })

  it('uses the explicit sheet of a cross-sheet reference', () => {
    const result = makeCell('/tmp/a.xlsx').calculate(
      infoType('FILENAME'),
      refOn('sheet-b') as never,
    ) as StringValueObject
    expect(result.getValue()).toBe('/tmp/[a.xlsx]Sheet 2')
  })

  it('falls back to the calling cell sheet when ref is omitted', () => {
    const result = makeCell('/tmp/a.xlsx').calculate(infoType('filename')) as StringValueObject
    expect(result.getValue()).toBe('/tmp/[a.xlsx]COUNT Functions')
  })

  it('returns an empty string for never-saved workbooks', () => {
    const result = makeCell(null).calculate(
      infoType('filename'),
      refOn(undefined, 'sheet-a') as never,
    ) as StringValueObject
    expect(result.getValue()).toBe('')
  })

  it('handles Windows separators', () => {
    const result = makeCell('C:\\Users\\x\\a.xlsx').calculate(
      infoType('filename'),
    ) as StringValueObject
    expect(result.getValue()).toBe('C:\\Users\\x\\[a.xlsx]COUNT Functions')
  })

  it('propagates info_type errors', () => {
    const error = ErrorValueObject.create('#NAME?' as never)
    expect(makeCell('/tmp/a.xlsx').calculate(error)).toBe(error)
  })
})

describe('CELL delegation', () => {
  it('routes every other info_type to the builtin executor', () => {
    const original = { calculate: vi.fn(() => StringValueObject.create('$B$4')) }
    const ref = refOn(undefined, 'sheet-a')
    const result = makeCell('/tmp/a.xlsx', original as never).calculate(
      infoType('address'),
      ref as never,
    )
    expect(original.calculate).toHaveBeenCalledWith(expect.anything(), ref)
    expect((result as StringValueObject).getValue()).toBe('$B$4')
  })

  it('returns #N/A for ref-less info_types other than filename', () => {
    const original = { calculate: vi.fn() }
    const result = makeCell('/tmp/a.xlsx', original as never).calculate(infoType('row'))
    expect((result as ErrorValueObject).getValue()).toBe('#N/A')
    expect(original.calculate).not.toHaveBeenCalled()
  })
})

it('cancels late registration and preserves a later executor owner on repeated disposal', async () => {
  const current = new BaseFunction('CELL')
  const later = new BaseFunction('CELL')
  let executor: BaseFunction | undefined = current
  const service = { getExecutor: () => executor, registerExecutors: (value: BaseFunction) => { executor = value }, unregisterExecutors: () => { executor = undefined } }
  const runtime = { univer: { __getInjector: () => ({ get: () => service }) } } as never
  const installed = installCellFilenameFunction(runtime, () => null)
  executor = later
  installed.dispose()
  installed.dispose()
  await new Promise(resolve => setTimeout(resolve, 5))
  expect(executor).toBe(later)
  expect(() => installCellFilenameFunction({ univer: {} }, () => null).dispose()).not.toThrow()
})

it('does not reclaim a later extension during the initialization timer', async () => {
  let executor: BaseFunction | undefined = new BaseFunction('CELL')
  const service = { getExecutor: () => executor, registerExecutors: (value: BaseFunction) => { executor = value }, unregisterExecutors: () => { executor = undefined } }
  const installed = installCellFilenameFunction({ univer: { __getInjector: () => ({ get: () => service }) } } as never, () => null)
  const later = new BaseFunction('CELL')
  executor = later
  await new Promise(resolve => setTimeout(resolve, 5))
  try { expect(executor).toBe(later) } finally { installed.dispose() }
})
