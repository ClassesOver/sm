import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { installCalculation, type CalculationControl } from './workbook-calculation'
import { mountWorkbookRibbon } from './workbook-ribbon'

// 下一批RED：只动态加载待实现产品，避免阻断当前批tsc，不把源helper当产品绿。
const implementation = './workbook-goal-seek'
type GoalSeekModule = {
  installGoalSeek(runtime: any, calculation: CalculationControl, protectedSheet?: (id: string) => boolean): {
    solve(input: { setCell: string; toValue: number; byCell: string }): Promise<{ found: boolean; reached: number; solution: number; iterations: number }>
    isRunning(): boolean
    dispose(): void
  }
}
async function product(): Promise<GoalSeekModule> { return import(/* @vite-ignore */ implementation) }
async function setup(formula = '=A1*2') {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
  const api = FUniver.newAPI(univer)
  const workbook = api.createWorkbook({ id: 'goal-seek', name: 'Goal seek', sheetOrder: ['data'], sheets: { data: {
    id: 'data', name: 'Data', rowCount: 20, columnCount: 10, cellData: { 0: { 0: { v: 10 }, 1: { f: formula } } },
  } } })
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const calculation = installCalculation({ univer } as any, () => false)
  return { univer, api, sheet: workbook.getActiveSheet()!, calculation, runtime: { univer, univerAPI: api } }
}

it('exposes the fixed-source Goal Seek entry for an editable workbook', () => {
  const host = document.createElement('main'); document.body.append(host)
  const ribbon = mountWorkbookRibbon(host, vi.fn(), { rotation: () => 0, editable: () => true })
  try {
    host.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
    const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="goal-seek-open"]')
    expect(button, '固定源存在Goal Seek，本地缺入口').not.toBeNull()
    expect(button!.disabled).toBe(false)
  } finally { ribbon.dispose(); host.remove() }
})

it.each([false, true])('solves through real Univer and keeps only the resulting input (manual=%s)', async manual => {
  const current = await setup()
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(20))
    current.calculation.setManual(manual)
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    const result = await installed.solve({ setCell: 'B1', toValue: 30, byCell: 'A1' })
    expect(result.found).toBe(true)
    expect(Math.abs(result.reached - 30)).toBeLessThanOrEqual(0.001)
    expect(result.solution).toBe(15)
    expect(result.iterations).toBeLessThanOrEqual(100)
    expect(current.sheet.getRange('A1').getValue()).toBe(15)
    expect(current.sheet.getRange('B1').getFormula()).toBe('=A1*2')
    expect(installed.isRunning()).toBe(false)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('reports the last unsuccessful guess but restores the source input when no solution exists', async () => {
  const current = await setup('=A1*0+5')
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(5))
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    const result = await installed.solve({ setCell: 'B1', toValue: 100, byCell: 'A1' })
    expect(result).toEqual({ found: false, reached: 5, solution: 11, iterations: 2 })
    expect(current.sheet.getRange('A1').getValue()).toBe(10)
    expect(current.sheet.getRange('B1').getFormula()).toBe('=A1*0+5')
    expect(installed.isRunning()).toBe(false)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('uses the fixed-source secant method for a nonlinear formula and retains per-guess undo', async () => {
  const current = await setup('=A1*A1')
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(100))
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    const result = await installed.solve({ setCell: 'B1', toValue: 4, byCell: 'A1' })
    expect(result.found).toBe(true)
    expect(Math.abs(result.reached - 4)).toBeLessThanOrEqual(0.001)
    expect(result.iterations).toBeGreaterThan(2)
    expect(result.iterations).toBeLessThanOrEqual(100)
    await current.api.undo()
    const previous = current.sheet.getRange('A1').getValue() as number
    expect(previous).not.toBe(result.solution)
    expect(previous).not.toBe(10) // 源逐guess journal，不要求一次undo回到原值。
    await current.api.redo()
    expect(current.sheet.getRange('A1').getValue()).toBeCloseTo(result.solution, 10)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('returns the initial solution in one evaluation when the target is already reached', async () => {
  const current = await setup()
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(20))
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    expect(await installed.solve({ setCell: 'B1', toValue: 20, byCell: 'A1' })).toEqual({ found: true, reached: 20, solution: 10, iterations: 1 })
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it('treats a later formula error as a dead end and restores the input', async () => {
  const current = await setup('=1/(A1-11)')
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(-1))
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    const result = await installed.solve({ setCell: 'B1', toValue: 0, byCell: 'A1' })
    expect(result).toMatchObject({ found: false, solution: 11, iterations: 2 })
    expect(Number.isNaN(result.reached)).toBe(true)
    expect(current.sheet.getRange('A1').getValue()).toBe(10)
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(-1))
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it('rejects a nonnumeric initial formula and restores an originally empty input', async () => {
  const current = await setup('=1/A1')
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    current.sheet.getRange('A1').setValue({ v: null })
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe('#DIV/0!'))
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    await expect(installed.solve({ setCell: 'B1', toValue: 1, byCell: 'A1' })).rejects.toThrow('返回数值')
    expect(current.sheet.getRange('A1').getValue()).toBeNull()
    expect(installed.isRunning()).toBe(false)
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it('refuses protected sheets, invalid input formulas and simultaneous solves before writing guesses', async () => {
  const current = await setup()
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(20))
    let protectedState = true
    installed = (await product()).installGoalSeek(current.runtime, current.calculation, () => protectedState)
    const input = { setCell: 'B1', toValue: 30, byCell: 'A1' }
    await expect(installed.solve(input)).rejects.toThrow('受保护')
    expect(installed.isRunning()).toBe(false)
    protectedState = false
    await expect(installed.solve({ ...input, byCell: 'B1' })).rejects.toThrow('不能含公式')
    await expect(installed.solve({ ...input, toValue: Number.NaN })).rejects.toThrow('有限数值')
    await expect(installed.solve({ ...input, byCell: 'XFE1' })).rejects.toThrow('边界')
    const pending = installed.solve(input)
    expect(installed.isRunning()).toBe(true)
    await expect(installed.solve(input)).rejects.toThrow('正在运行')
    await pending
  } finally { installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})

it.each(['dispose', 'recreate'])('protects source core identity during %s while an evaluation is pending', async fault => {
  const current = await setup(), { ICommandService } = await import('@univerjs/core')
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined, listener: { dispose(): void } | undefined
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(20))
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    let writes = 0
    listener = current.univer.__getInjector().get(ICommandService).onCommandExecuted(command => {
      if (command.id !== 'sheet.command.set-range-values' || ++writes !== 2) return
      if (fault === 'dispose') installed!.dispose()
      else {
        current.api.disposeUnit('goal-seek')
        current.api.createWorkbook({ id: 'goal-seek', name: 'New core', sheetOrder: ['data'], sheets: { data: {
          id: 'data', name: 'Data', rowCount: 20, columnCount: 10, cellData: { 0: { 0: { v: 999 } } },
        } } })
        current.univer.__getInjector().get(IUniverInstanceService).focusUnit('goal-seek')
      }
    })
    await expect(installed.solve({ setCell: 'B1', toValue: 30, byCell: 'A1' })).rejects.toThrow(fault === 'dispose' ? '取消' : '变化')
    expect(current.api.getActiveWorkbook()!.getActiveSheet()!.getRange('A1').getValue()).toBe(fault === 'dispose' ? 10 : 999)
    expect(installed.isRunning()).toBe(false)
  } finally { listener?.dispose(); installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
}, 15000)

it('restores the original input after an explicitly rejected second official guess write', async () => {
  const current = await setup(), { ICommandService } = await import('@univerjs/core')
  let installed: ReturnType<GoalSeekModule['installGoalSeek']> | undefined, restore = () => {}
  try {
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(20))
    const commands = current.univer.__getInjector().get(ICommandService), execute = commands.syncExecuteCommand.bind(commands)
    let writes = 0
    const spy = vi.spyOn(commands, 'syncExecuteCommand').mockImplementation(((id: string, params: any, options: any) => {
      if (id === 'sheet.command.set-range-values' && ++writes === 2) return false
      return execute(id, params, options)
    }) as typeof commands.syncExecuteCommand)
    restore = () => { spy.mockRestore() }
    installed = (await product()).installGoalSeek(current.runtime, current.calculation)
    await expect(installed.solve({ setCell: 'B1', toValue: 30, byCell: 'A1' })).rejects.toThrow('未执行')
    expect(writes).toBe(3) // 两次尝试，加一次官方恢复写；不伪造引擎结果。
    expect(current.sheet.getRange('A1').getValue()).toBe(10)
    expect(current.sheet.getRange('B1').getFormula()).toBe('=A1*2')
    expect(installed.isRunning()).toBe(false)
    await vi.waitFor(() => expect(current.sheet.getRange('B1').getValue()).toBe(20))
  } finally { restore(); installed?.dispose(); current.calculation.dispose(); current.univer.dispose() }
})
