import { expect, it, vi } from 'vitest'
import { IUniverInstanceService, LocaleType, Univer, type ICellData } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsNumfmtPlugin } from '@univerjs/sheets-numfmt'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { installCalculation } from './workbook-calculation'
import { installGoalSeek } from './workbook-goal-seek'
import { installDataTable } from './workbook-data-table'

// 真实NUMFMT拦截器将数值投影为显示字符串；模拟分析必须使用原始值，不能解析显示文案。
function fixture(kind: 'goal' | 'table', formatted: string) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverSheetsNumfmtPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const api = FUniver.newAPI(univer), number = { n: { pattern: '0.00' } }, percent = { n: { pattern: '0.0%' } }
  const cellData: Record<number, Record<number, ICellData>> = kind === 'goal'
    ? { 0: { 0: { v: 0.25, ...(formatted === 'input' ? { s: percent } : {}) }, 1: { f: '=A1*2', s: percent } } }
    : { 0: { 3: { v: 10, ...(formatted === 'input' ? { s: { n: { pattern: '$0.00' } } } : {}) } },
      3: { 2: { f: '=D1*2', ...(formatted === 'formula' ? { s: number } : {}) } },
      4: { 1: { v: 0.125, ...(formatted === 'candidates' ? { s: percent } : {}) } },
      5: { 1: { v: 0.25, ...(formatted === 'candidates' ? { s: percent } : {}) } },
      6: { 1: { v: 0.375, ...(formatted === 'candidates' ? { s: percent } : {}) } } }
  const workbook = api.createWorkbook({ id: 'analysis-formatted', name: 'Analysis', sheetOrder: ['data'], sheets: {
    data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 10, cellData },
  } })
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const calculation = installCalculation({ univer } as any, () => false)
  return { univer, api, sheet: workbook.getActiveSheet()!, calculation, runtime: { univer, univerAPI: api } }
}

it.each(['input', 'formula'])('solves a percentage-formatted %s without treating its displayed text as a number', async formatted => {
  const f = fixture('goal', formatted), solver = installGoalSeek(f.runtime, f.calculation)
  try {
    await vi.waitFor(() => expect(f.sheet.getRange('B1').getRawValue()).toBe(0.5))
    expect(f.sheet.getRange('B1').getValue()).toBe('50.0%')
    const before = structuredClone(f.sheet.getSheet().getCellMatrix().getValue(0, 1)?.s)
    f.calculation.setManual(formatted === 'formula')
    const result = await solver.solve({ setCell: 'B1', toValue: 0.6, byCell: 'A1' })
    expect(result.found).toBe(true)
    expect(result.solution).toBeCloseTo(0.3, 10)
    expect(f.sheet.getRange('A1').getRawValue()).toBeCloseTo(0.3, 10)
    expect(f.sheet.getRange('B1').getRawValue()).toBeCloseTo(0.6, 10)
    expect(f.sheet.getRange('B1').getFormula()).toBe('=A1*2')
    expect(f.sheet.getSheet().getCellMatrix().getValue(0, 1)?.s).toEqual(before)
  } finally { solver.dispose(); f.calculation.dispose(); f.univer.dispose() }
}, 15000)

it.each(['input', 'candidates', 'formula'])('keeps numeric data-table results when the %s has a display format', async formatted => {
  const f = fixture('table', formatted), table = installDataTable(f.runtime, f.calculation)
  try {
    await vi.waitFor(() => expect(f.sheet.getRange('C4').getRawValue()).toBe(20))
    if (formatted === 'candidates') expect(f.sheet.getRange('B5').getValue()).toBe('12.5%')
    if (formatted === 'formula') expect(f.sheet.getRange('C4').getValue()).toBe('20.00')
    f.calculation.setManual(formatted === 'formula')
    expect(await table.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1' })).toEqual({ kind: 'column', cells: 3 })
    expect(['C5', 'C6', 'C7'].map(address => f.sheet.getRange(address).getRawValue())).toEqual([0.25, 0.5, 0.75])
    expect(f.sheet.getRange('D1').getRawValue()).toBe(10)
    expect(f.sheet.getRange('C4').getFormula()).toBe('=D1*2')
    await f.api.undo()
    expect(['C5', 'C6', 'C7'].map(address => f.sheet.getRange(address).getRawValue())).toEqual([null, null, null])
    expect(f.sheet.getRange('D1').getRawValue()).toBe(10)
    await f.api.redo()
    expect(['C5', 'C6', 'C7'].map(address => f.sheet.getRange(address).getRawValue())).toEqual([0.25, 0.5, 0.75])
  } finally { table.dispose(); f.calculation.dispose(); f.univer.dispose() }
}, 15000)
