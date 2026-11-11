import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { installCalculation, type CalculationControl } from './workbook-calculation'

// 动态路径允许独立 RED 在未实现时编译；并不把上游 helper 当本产品实现。
const implementation = './workbook-data-table'
type Cell = { row: number; column: number }
type Bounds = { startRow: number; endRow: number; startColumn: number; endColumn: number }
type Input = { tableRange: string; rowInputCell: string | null; columnInputCell: string | null; onProgress?: (done: number, total: number) => void }
type DataTableModule = {
  planDataTable(bounds: Bounds, row: Cell | null, column: Cell | null): any
  installDataTable(runtime: any, calculation: CalculationControl, protectedSheet?: (id: string) => boolean): {
    apply(input: Input): Promise<{ kind: string; cells: number }>
    dispose(): void
    isRunning(): boolean
  }
}
async function product(): Promise<DataTableModule> { return import(/* @vite-ignore */ implementation) }

it('plans three source layouts and rejects destructive inputs and excess result cells', async () => {
  const { planDataTable } = await product()
  const bounds = { startRow: 3, endRow: 6, startColumn: 1, endColumn: 2 }, input = { row: 0, column: 3 }
  expect(planDataTable(bounds, null, input)).toMatchObject({ kind: 'column', formulaCell: { row: 3, column: 2 }, resultRows: 3, resultColumns: 1, resultStart: { row: 4, column: 2 } })
  expect(planDataTable({ startRow: 0, endRow: 1, startColumn: 0, endColumn: 3 }, { row: 3, column: 5 }, null)).toMatchObject({ kind: 'row', resultRows: 1, resultColumns: 3 })
  expect(planDataTable(bounds, input, { row: 0, column: 4 })).toMatchObject({ kind: 'grid', resultRows: 3, resultColumns: 1 })
  expect(planDataTable(bounds, null, null)).toBe('noInputCell')
  expect(planDataTable(bounds, input, input)).toBe('sameInputCell')
  expect(planDataTable(bounds, null, { row: 4, column: 1 })).toBe('inputInsideTable')
  expect(planDataTable({ ...bounds, endColumn: 3 }, null, input)).toBe('badShape')
  expect(planDataTable({ startRow: 0, endRow: 10001, startColumn: 0, endColumn: 1 }, null, input)).toBe('tooManyCells')
})

async function realWorkbook() {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const api = FUniver.newAPI(univer)
  const workbook = api.createWorkbook({ id: 'data-table', name: 'Data table', sheetOrder: ['data'], sheets: { data: {
    id: 'data', name: 'Data', rowCount: 30, columnCount: 20, cellData: {
      0: { 3: { v: 10 }, 4: { v: 100 } }, 3: { 2: { f: '=D1*2' } },
      4: { 1: { v: 1 } }, 5: { 1: { v: 2 } }, 6: { 1: { v: 3 } },
      9: { 1: { f: '=D1+E1' }, 2: { v: 1 }, 3: { v: 2 } },
      10: { 1: { v: 10 } }, 11: { 1: { v: 20 } },
      14: { 1: { v: 1 }, 2: { v: 2 }, 3: { v: 3 } }, 15: { 0: { f: '=D1*2' } },
    },
  } } })
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const calculation = installCalculation({ univer } as any, () => false), runtime = { univer, univerAPI: api }
  return { univer, api, sheet: workbook.getActiveSheet()!, calculation, runtime }
}

it.each([false, true])('calculates real column results, restores inputs and uses one undo/redo (manual=%s)', async manual => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
    current.calculation.setManual(manual)
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    const onProgress = vi.fn()
    expect(await installed.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1', onProgress })).toEqual({ kind: 'column', cells: 3 })
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[2], [4], [6]])
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    expect(current.sheet.getRange('C4').getFormula()).toBe('=D1*2')
    expect(current.sheet.getRange('C5:C7').getFormulas()).toEqual([[''], [''], ['']])
    expect(onProgress.mock.calls).toEqual([[1, 3], [2, 3], [3, 3]])
    await current.api.undo()
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[null], [null], [null]])
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    await current.api.redo()
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[2], [4], [6]])
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('calculates a real two-input static grid while restoring both inputs', async () => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B10').getValue()).toBe(110))
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    expect(await installed.apply({ tableRange: 'B10:D12', rowInputCell: 'D1', columnInputCell: 'E1' })).toEqual({ kind: 'grid', cells: 4 })
    expect(current.sheet.getRange('C11:D12').getValues()).toEqual([[11, 12], [21, 22]])
    expect(current.sheet.getRange('D1:E1').getValues()).toEqual([[10, 100]])
    await current.api.undo()
    expect(current.sheet.getRange('C11:D12').getValues()).toEqual([[null, null], [null, null]])
    expect(current.sheet.getRange('D1:E1').getValues()).toEqual([[10, 100]])
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it.each(['progress-failure', 'disposed'])('restores real inputs and removes the failed undo batch (%s)', async fault => {
  const current = await realWorkbook(), { IUndoRedoService } = await import('@univerjs/core')
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
    const history = current.univer.__getInjector().get(IUndoRedoService), before = history.pitchTopUndoElement()
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    const applying = installed.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1', onProgress(done) {
      expect(installed!.isRunning()).toBe(true)
      if (done === 2) {
        if (fault === 'disposed') installed!.dispose()
        else throw new Error('injected read failure')
      }
    } })
    expect(installed.isRunning()).toBe(true)
    await expect(applying).rejects.toThrow(fault === 'disposed' ? '变化' : 'injected read failure')
    expect(installed.isRunning()).toBe(false)
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[null], [null], [null]])
    expect(history.pitchTopUndoElement()).toBe(before)
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it('rejects protected input writes before starting and refuses a concurrent calculation', async () => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
    let protectedState = true
    installed = (await product()).installDataTable(current.runtime, current.calculation, () => protectedState)
    const input = { tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1' }
    await expect(installed.apply(input)).rejects.toThrow('受保护')
    expect(installed.isRunning()).toBe(false)
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    protectedState = false
    const applying = installed.apply(input)
    await expect(installed.apply(input)).rejects.toThrow('正在计算')
    await applying
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it('never restores old input values into a recreated core with the same workbook identity', async () => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    await expect(installed.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1', onProgress(done) {
      if (done !== 1) return
      current.api.disposeUnit('data-table')
      current.api.createWorkbook({ id: 'data-table', name: 'Replacement', sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 30, columnCount: 20, cellData: { 0: { 3: { v: 999 } } } } } })
      current.univer.__getInjector().get(IUniverInstanceService).focusUnit('data-table')
    } })).rejects.toThrow('变化')
    expect(current.api.getActiveWorkbook()!.getActiveSheet()!.getRange('D1').getValue()).toBe(999)
    expect(installed.isRunning()).toBe(false)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it('finishes when restoring an input already equal to the last candidate', async () => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
    current.sheet.getRange('B7').setValue(10)
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    await installed.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1' })
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[2], [4], [20]])
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    await current.api.undo()
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[null], [null], [null]])
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    expect(current.sheet.getRange('B7').getValue()).toBe(10)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('calculates a real row-oriented table and keeps the source formula outside the result block', async () => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('A16').getValue()).toBe(20))
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    expect(await installed.apply({ tableRange: 'A15:D16', rowInputCell: 'D1', columnInputCell: null })).toEqual({ kind: 'row', cells: 3 })
    expect(current.sheet.getRange('B16:D16').getValues()).toEqual([[2, 4, 6]])
    expect(current.sheet.getRange('A16').getFormula()).toBe('=D1*2')
    await current.api.undo()
    expect(current.sheet.getRange('B16:D16').getValues()).toEqual([[null, null, null]])
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('rolls back an explicitly rejected intermediate official write without leaving history', async () => {
  const current = await realWorkbook(), { ICommandService, IUndoRedoService } = await import('@univerjs/core')
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  let restore = () => {}
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(20))
    const commands = current.univer.__getInjector().get(ICommandService), execute = commands.syncExecuteCommand.bind(commands)
    const history = current.univer.__getInjector().get(IUndoRedoService), previous = history.pitchTopUndoElement()
    let writes = 0
    const interception = vi.spyOn(commands, 'syncExecuteCommand').mockImplementation(((id: string, params: any, options: any) => {
      if (id === 'sheet.command.set-range-values' && ++writes === 2) return false
      return execute(id, params, options)
    }) as typeof commands.syncExecuteCommand)
    restore = () => { interception.mockRestore() }
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    await expect(installed.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1' })).rejects.toThrow('未执行')
    expect(current.sheet.getRange('D1').getValue()).toBe(10)
    expect(history.pitchTopUndoElement()).toBe(previous)
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual([[null], [null], [null]])
  } finally { restore(); installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it.each<[string, string[]]>([
  ['="="&D1', ['=1', '=2', '=3']],
  ['=1/(D1-D1)', ['#DIV/0!', '#DIV/0!', '#DIV/0!']],
])('keeps formula output %s as static text in the grid and real XLSX serialization', async (formula, expected) => {
  const current = await realWorkbook()
  let installed: ReturnType<DataTableModule['installDataTable']> | undefined
  try {
    current.sheet.getRange('C4').setValue({ f: formula, v: null })
    await vi.waitFor(() => expect(current.sheet.getRange('C4').getValue()).toBe(formula.startsWith('="="') ? '=10' : '#DIV/0!'))
    installed = (await product()).installDataTable(current.runtime, current.calculation)
    await installed.apply({ tableRange: 'B4:C7', rowInputCell: null, columnInputCell: 'D1' })
    expect(current.sheet.getRange('C5:C7').getValues()).toEqual(expected.map(value => [value]))
    expect(current.sheet.getRange('C5:C7').getFormulas()).toEqual([[''], [''], ['']])
    const { createBlankWorkbook, applyCellEdits, readWorkbook, createBufferEntrySource } = await import('@sheets-web/xlsx-engine')
    const saved = await applyCellEdits(await createBlankWorkbook('Data'), [
      { sheetName: 'Data', row: 3, column: 2, writeValue: true, cell: { formula, value: null } },
      ...current.sheet.getRange('C5:C7').getValues().map((row, index) => ({ sheetName: 'Data', row: index + 4, column: 2, writeValue: true, cell: { value: row[0] ?? null } })),
    ])
    const model = (await readWorkbook(saved)).sheets[0]!
    for (let index = 0; index < expected.length; index++) expect(model.cells[`C${index + 5}`]).toMatchObject({ value: expected[index] })
    for (const cell of ['C5', 'C6', 'C7']) expect(model.cells[cell]?.formula).toBeUndefined()
    expect(model.cells.C4?.formula).toBe(formula)
    const xml = await (await createBufferEntrySource(saved)).readText('xl/worksheets/sheet1.xml')
    for (const cell of ['C5', 'C6', 'C7']) expect(xml.match(new RegExp(`<c\\b[^>]*r="${cell}"[^>]*>[\\s\\S]*?</c>`))?.[0]).not.toContain('<f>')
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)
