import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { mountWorkbookRibbon } from './workbook-ribbon'

it('exposes fixed-source Consolidate for an editable workbook', () => {
  const host = document.createElement('main'); document.body.append(host)
  const ribbon = mountWorkbookRibbon(host, vi.fn(), { rotation: () => 0, editable: () => true })
  try {
    host.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
    const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="consolidate-open"]')
    expect(button).not.toBeNull()
    expect(button!.disabled, button!.title).toBe(false)
  } finally { ribbon.dispose(); host.remove() }
})

// 这是原生协议探针，不能代替尚未实现的产品合并计算测试。
it('native worksheet writes source-shaped cross-sheet aggregation formulas in one undoable matrix', async () => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const api = FUniver.newAPI(univer)
  const makeSheet = (id: string, name: string, rows: [string, number][]) => ({ id, name, rowCount: 20, columnCount: 10,
    cellData: Object.fromEntries(rows.map(([label, value], row) => [row, { 0: { v: label }, 1: { v: value } }])),
  })
  const workbook = api.createWorkbook({ id: 'consolidate-native', name: 'Consolidate', sheetOrder: ['out', 'first', 'second'], sheets: {
    out: makeSheet('out', 'Output', []), first: makeSheet('first', 'Source One', [['East', 10], ['West', 20], ['East', 5]]),
    second: makeSheet('second', "O'Brien", [['East', 7], ['North', 3]]),
  } })
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const sheet = workbook.getActiveSheet()!
  try {
    const sum = "SUMIF('Source One'!$A$1:$A$3,$A5,'Source One'!B1:B3)+SUMIF('O''Brien'!$A$1:$A$2,$A5,'O''Brien'!B1:B2)"
    const count = "COUNTIF('Source One'!$A$1:$A$3,$A5)+COUNTIF('O''Brien'!$A$1:$A$2,$A5)"
    sheet.getRange('A5:E5').setValues([[{ v: 'East' }, { f: `=${sum}` }, { f: `=${count}` }, { f: `=(${sum})/(${count})` }, { f: "=SUM('Source One'!B1,'O''Brien'!B1)" }]])
    const assertCalculated = () => {
      expect(sheet.getRange('B5:C5').getValues()).toEqual([[22, 3]])
      expect(sheet.getRange('D5').getValue()).toBeCloseTo(22 / 3, 10)
      expect(sheet.getRange('E5').getValue()).toBe(17)
    }
    await vi.waitFor(assertCalculated)
    expect(sheet.getRange('B5').getFormula()).toBe(`=${sum}`)
    expect(sheet.getRange('A5').getFormula()).toBe('')
    await api.undo()
    expect(sheet.getRange('A5:E5').getValues()).toEqual([[null, null, null, null, null]])
    await api.redo()
    await vi.waitFor(assertCalculated)
  } finally { univer.dispose() }
})

const implementation = './workbook-consolidate'
type Input = { fn: 'sum' | 'count' | 'average' | 'max' | 'min'; references: string[]; leftLabels: boolean }
async function product(): Promise<{ applyConsolidate(runtime: any, input: Input, protectedSheet?: (id: string) => boolean, beforeWrite?: (params: any) => void): { rows: number; columns: number; sources: number }; parseConsolidateReference(text: string): any }> { return import(/* @vite-ignore */ implementation) }
async function productWorkbook() {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const api = FUniver.newAPI(univer)
  const sheetData = (id: string, name: string, rows: [string, number][]) => ({ id, name, rowCount: 30, columnCount: 10,
    cellData: Object.fromEntries(rows.map(([label, value], row) => [row, { 0: { v: label }, 1: { v: value } }])),
  })
  const workbook = api.createWorkbook({ id: 'consolidate-product', name: 'Consolidate', sheetOrder: ['out', 'a', 'b'], sheets: {
    out: sheetData('out', 'Output', []), a: sheetData('a', 'Source One', [['East', 10], ['West', 20], ['East', 5]]),
    b: sheetData('b', "O'Brien", [['East', 7], ['North', 3]]),
  } })
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const sheet = workbook.getActiveSheet()!
  sheet.getRange('A5').activate()
  return { univer, api, workbook, sheet, runtime: { univer, univerAPI: api } }
}
const references = ["'source one'!$A$1:$B$3", "'O''Brien'!A1:B2"]
it.each(['sum', 'count', 'average', 'max', 'min'] as const)('product consolidates unequal positional sources using %s and one undo', async fn => {
  const c = await productWorkbook()
  try {
    const { applyConsolidate } = await product()
    expect(applyConsolidate(c.runtime, { fn, references, leftLabels: false })).toEqual({ rows: 3, columns: 2, sources: 2 })
    const names = { sum: 'SUM', count: 'COUNTA', average: 'AVERAGE', max: 'MAX', min: 'MIN' }
    expect(c.sheet.getRange('B5').getFormula()).toBe(`=${names[fn]}('Source One'!B1,'O''Brien'!B1)`)
    expect(c.sheet.getRange('B7').getFormula()).toBe(`=${names[fn]}('Source One'!B3)`)
    const values = { sum: 17, count: 2, average: 8.5, max: 10, min: 7 }
    await vi.waitFor(() => expect(c.sheet.getRange('B5').getValue()).toBe(values[fn]))
    await c.api.undo()
    expect(c.sheet.getRange('A5:B7').getValues()).toEqual([[null, null], [null, null], [null, null]])
    await c.api.redo()
    await vi.waitFor(() => expect(c.sheet.getRange('B5').getValue()).toBe(values[fn]))
  } finally { c.univer.dispose() }
})
it.each(['sum', 'count', 'average'] as const)('product matches repeated left labels in first-seen order using %s', async fn => {
  const c = await productWorkbook()
  try {
    const { applyConsolidate } = await product()
    expect(applyConsolidate(c.runtime, { fn, references, leftLabels: true })).toEqual({ rows: 3, columns: 2, sources: 2 })
    expect(c.sheet.getRange('A5:A7').getValues()).toEqual([['East'], ['West'], ['North']])
    const expected = { sum: [22, 20, 3], count: [3, 1, 1], average: [22 / 3, 20, 3] }[fn]
    await vi.waitFor(() => expected.forEach((value, row) => expect(c.sheet.getRange(row + 4, 1, 1, 1).getValue()).toBeCloseTo(value, 10)))
    expect(c.sheet.getRange('B5').getFormula()).toContain("'Source One'!$A$1:$A$3,$A5")
    expect(c.sheet.getRange('B7').getFormula()).not.toContain('Source One')
  } finally { c.univer.dispose() }
})
it('product rejects invalid sources, overlap, bounds, label shape and protection without writing', async () => {
  const c = await productWorkbook()
  try {
    const { applyConsolidate, parseConsolidateReference } = await product()
    expect(parseConsolidateReference("'O''Brien'!$a$1:$b$2")).toMatchObject({ sheetName: "O'Brien", range: { endRow: 1, endColumn: 1 } })
    expect(parseConsolidateReference('A0')).toBeNull()
    for (const input of [
      { fn: 'sum', references: [], leftLabels: false },
      { fn: 'sum', references: ['Missing!A1'], leftLabels: false },
      { fn: 'sum', references: ['A5:B7'], leftLabels: false },
      { fn: 'sum', references: ['XFE1'], leftLabels: false },
      { fn: 'sum', references: ["'Source One'!A1:A3"], leftLabels: true },
      { fn: 'max', references, leftLabels: true },
      { fn: 'min', references, leftLabels: true },
      { fn: 'sum', references: ['A1:B3'], leftLabels: true },
    ] as Input[]) expect(() => applyConsolidate(c.runtime, input)).toThrow()
    expect(() => applyConsolidate(c.runtime, { fn: 'sum', references, leftLabels: false }, () => true)).toThrow('保护')
    expect(c.sheet.getRange('A5:B7').getValues()).toEqual([[null, null], [null, null], [null, null]])
    c.sheet.getSheet().setRowCount(1048576); c.sheet.getSheet().setColumnCount(16384)
    c.sheet.getRange('XFD1048576').activate()
    expect(() => applyConsolidate(c.runtime, { fn: 'sum', references, leftLabels: false })).toThrow('边界')
  } finally { c.univer.dispose() }
})

it('product preserves formula-like and quoted labels as text and keeps native SUMIF wildcard semantics', async () => {
  const c = await productWorkbook()
  try {
    const source = c.workbook.getSheetBySheetId('a')!
    source.getRange('A1:A3').setValues([[{ v: '=1+1', t: 1, f: null }], [{ v: "O'Brien" }], [{ v: '*' }]])
    const { applyConsolidate } = await product()
    applyConsolidate(c.runtime, { fn: 'sum', references: ["'Source One'!A1:B3"], leftLabels: true })
    expect(c.sheet.getRange('A5:A7').getValues()).toEqual([['=1+1'], ["O'Brien"], ['*']])
    expect(c.sheet.getRange('A5').getFormula()).toBe('')
    // 固定源直接使用标签单元格作criteria；'=1+1'是原生比较条件，'*'是通配符。
    await vi.waitFor(() => expect(c.sheet.getRange('B5:B7').getValues()).toEqual([[0], [20], [35]]))
  } finally { c.univer.dispose() }
})

it('product rejects a full-sheet positional matrix before allocation using the existing cell edit budget', async () => {
  const c = await productWorkbook()
  try {
    const { applyConsolidate } = await product()
    c.sheet.getRange('A1').activate()
    expect(() => applyConsolidate(c.runtime, { fn: 'sum', references: ["'Source One'!A1:XFD1048576"], leftLabels: false })).toThrow('预算')
    expect(c.sheet.getRange('A1').getValue()).toBeNull()
  } finally { c.univer.dispose() }
})

it('product clears stale formulas in uncovered positional cells and replaces typed text with formulas', async () => {
  const c = await productWorkbook()
  try {
    c.sheet.getRange('A5:C7').setValues([[{ v: 'old text', t: 1 }, { f: '=99' }, { f: '=99' }], [{ f: '=99' }, { f: '=99' }, { f: '=99' }], [{ f: '=99' }, { f: '=99' }, { f: '=99' }]])
    const { applyConsolidate } = await product()
    expect(applyConsolidate(c.runtime, { fn: 'count', references: ["'Source One'!A1:A3", "'O''Brien'!A1:C1"], leftLabels: false })).toEqual({ rows: 3, columns: 3, sources: 2 })
    await vi.waitFor(() => expect(c.sheet.getRange('A5:C7').getValues()).toEqual([[2, 1, 0], [1, null, null], [1, null, null]]))
    expect(c.sheet.getRange('B6:C7').getFormulas()).toEqual([['', ''], ['', '']])
  } finally { c.univer.dispose() }
})

it('product propagates a rejected official write without reporting success', async () => {
  const c = await productWorkbook()
  try {
    const { ICommandService } = await import('@univerjs/core')
    const commands = c.univer.__getInjector().get(ICommandService)
    const rejected = vi.spyOn(commands, 'syncExecuteCommand').mockReturnValue(false)
    const { applyConsolidate } = await product()
    try { expect(() => applyConsolidate(c.runtime, { fn: 'sum', references, leftLabels: false })).toThrow('写入未执行') }
    finally { rejected.mockRestore() }
    expect(c.sheet.getRange('A5:B7').getValues()).toEqual([[null, null], [null, null], [null, null]])
  } finally { c.univer.dispose() }
})


it('product offers the native payload to budget preflight and aborts all writes if preflight rejects', async () => {
  const c = await productWorkbook()
  try {
    const { applyConsolidate } = await product()
    const beforeWrite = vi.fn((params: any) => {
      expect(params).toMatchObject({ unitId: 'consolidate-product', subUnitId: 'out', value: { 4: { 0: { v: 'East', t: 1, f: null, p: null }, 1: { v: null, p: null } } } })
      expect(params.value[4][1].f).toContain('SUMIF(')
      throw new Error('injected existing draft budget rejection')
    })
    expect(() => applyConsolidate(c.runtime, { fn: 'sum', references, leftLabels: true }, undefined, beforeWrite)).toThrow('existing draft budget')
    expect(beforeWrite).toHaveBeenCalledTimes(1)
    expect(c.sheet.getRange('A5:B7').getValues()).toEqual([[null, null], [null, null], [null, null]])
  } finally { c.univer.dispose() }
})
