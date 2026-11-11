import { expect, it, vi } from 'vitest'
import { Univer, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { installIfsEmptySetFix } from './workbook-function-ifs'

it.each(['MINIFS', 'MAXIFS'])('returns numeric zero for a real Univer %s formula with no criteria match', async name => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const installed = installIfsEmptySetFix({ univer })
  const api = FUniver.newAPI(univer)
  try {
    const book = api.createWorkbook({ id: `ifs-${name}`, name: 'IFS', sheetOrder: ['data'], sheets: { data: {
      id: 'data', name: 'Data', rowCount: 20, columnCount: 10,
      cellData: { 0: { 0: { v: -3 }, 1: { v: 'yes' }, 2: { f: `=${name}(A1:A3,B1:B3,"missing")` } }, 1: { 0: { v: 0 }, 1: { v: 'yes' } }, 2: { 0: { v: 7 }, 1: { v: 'no' } } },
    } } })
    const sheet = book.getActiveSheet()!
    await vi.waitFor(() => expect(sheet.getRange('C1').getValue()).toBe(0))
  } finally { installed.dispose(); univer.dispose() }
}, 10000)

it.each(['MINIFS', 'MAXIFS'])('keeps real zero, negative values, conditions, errors and array expansion for %s', async name => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const installed = installIfsEmptySetFix({ univer }), api = FUniver.newAPI(univer)
  const cases: [string, number | string][] = [
    [`${name}(A1:A4,B1:B4,"yes")`, name === 'MINIFS' ? -3 : 0],
    [`${name}(A1:A4,A1:A4,">=0")`, name === 'MINIFS' ? 0 : 7],
    [`${name}(A1:A4,B1:B4,"Ye?")`, name === 'MINIFS' ? -3 : 0],
    [`${name}(A1:A4,B1:B4,"~*")`, -11],
    [`${name}(A1:A4,B1:B4,"yes",A1:A4,">=0")`, 0],
    [`${name}(A1:A5,B1:B5,"error")`, '#DIV/0!'],
    [`${name}(A1:A4,B1:B3,"yes")`, '#VALUE!'],
  ]
  try {
    const cellData: Record<number, Record<number, { v?: number | string; f?: string }>> = {
      0: { 0: { v: -3 }, 1: { v: 'yes' } }, 1: { 0: { v: 0 }, 1: { v: 'yes' } },
      2: { 0: { v: 7 }, 1: { v: 'no' } }, 3: { 0: { v: -11 }, 1: { v: '*' } },
      4: { 0: { f: '=1/0' }, 1: { v: 'error' } },
    }
    cases.forEach(([formula], row) => { (cellData[row] ??= {})[2] = { f: `=${formula}` } })
    cellData[8] = { 2: { f: `=${name}(A1:A4,B1:B4,{"yes","missing"})` } }
    const book = api.createWorkbook({ id: `ifs-cases-${name}`, name: 'IFS cases', sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 10, cellData } } })
    const sheet = book.getActiveSheet()!
    await vi.waitFor(() => {
      cases.forEach(([, value], row) => expect(sheet.getRange(`C${row + 1}`).getValue()).toBe(value))
      expect(sheet.getRange('C9').getValue()).toBe(name === 'MINIFS' ? -3 : 0)
      expect(sheet.getRange('D9').getValue()).toBe(0)
    })
  } finally { installed.dispose(); univer.dispose() }
}, 10000)
