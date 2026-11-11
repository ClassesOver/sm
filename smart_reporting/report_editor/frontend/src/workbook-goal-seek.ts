import { ICommandService } from '@univerjs/core'
import { parseAddress } from '@sheets-web/xlsx-engine'
import type { CalculationControl } from './workbook-calculation'

export interface GoalSeekInput { setCell: string; toValue: number; byCell: string }
export interface GoalSeekResult { found: boolean; reached: number; solution: number; iterations: number }
const MAX_ITERATIONS = 100
const MAX_CHANGE = 0.001

// 固定源goal-seek.ts：逐次官方写入并等待原生计算，割线求解；不合并guess撤销历史。
export function installGoalSeek(runtime: any, calculation: CalculationControl, protectedSheet: (id: string) => boolean = () => false) {
  const commands = runtime.univer.__getInjector().get(ICommandService)
  let disposed = false, running = false, cancel: (() => void) | undefined
  return {
    isRunning: () => running,
    dispose() { disposed = true; cancel?.() },
    async solve(input: GoalSeekInput): Promise<GoalSeekResult> {
      if (disposed) throw new Error('单变量求解已关闭')
      if (running) throw new Error('单变量求解正在运行，请稍候')
      const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
      if (!sheet) throw new Error('当前没有可编辑工作表')
      if (!Number.isFinite(input.toValue)) throw new Error('目标值必须为有限数值')
      const unitId = workbook.getId(), subUnitId = sheet.getSheetId(), core = workbook.getWorkbook(), sheetCore = sheet.getSheet()
      const valid = () => runtime.univerAPI.getActiveWorkbook()?.getWorkbook() === core && workbook.getSheetBySheetId(subUnitId)?.getSheet() === sheetCore
      const check = () => { if (disposed || !valid()) throw new Error('单变量求解来源已变化，请重新打开对话框') }
      if (protectedSheet(subUnitId)) throw new Error('工作表受保护，请先撤销保护')
      const address = (value: string) => {
        const cell = parseAddress(value.trim().toUpperCase())
        if (cell.row > 1048575 || cell.column > 16383) throw new Error('单元格超出工作表边界')
        return cell
      }
      const target = address(input.setCell), changing = address(input.byCell)
      const targetRange = sheet.getRange(target.row, target.column, 1, 1), changingRange = sheet.getRange(changing.row, changing.column, 1, 1)
      if (!targetRange.getFormula()) throw new Error('目标单元格必须包含公式')
      const original = changingRange.getValue()
      if (changingRange.getFormula() || original != null && typeof original !== 'number') throw new Error('可变单元格必须为空或数值，不能含公式')
      const write = (value: number | null) => {
        if (!commands.syncExecuteCommand('sheet.command.set-range-values', { unitId, subUnitId,
          range: { startRow: changing.row, endRow: changing.row, startColumn: changing.column, endColumn: changing.column },
          value: { v: value, f: null, p: null },
        })) throw new Error('单变量求解写入未执行')
      }
      const recalc = (mutate: () => void) => new Promise<void>((resolve, reject) => {
        const finish = (error?: Error) => { subscription.dispose(); clearTimeout(timer); cancel = undefined; error ? reject(error) : resolve() }
        const subscription = runtime.univerAPI.getFormula().calculationEnd(() => finish())
        // 固定源允许等值写入无新计算事件，2秒结束等待。
        const timer = setTimeout(() => finish(), 2000)
        cancel = () => finish(new Error('单变量求解已取消'))
        try { mutate(); if (calculation.manual()) calculation.calculateNow() } catch (error) { finish(error as Error) }
      })
      const evaluate = async (value: number) => {
        check(); await recalc(() => write(value)); check()
        const reached = targetRange.getValue()
        return typeof reached === 'number' ? reached : Number.NaN
      }
      const restore = async () => { if (valid()) await recalc(() => write(original ?? null)) }
      running = true
      try {
        let x0 = original ?? 0, f0 = await evaluate(x0)
        if (Number.isNaN(f0)) throw new Error('目标公式必须返回数值')
        if (Math.abs(f0 - input.toValue) <= MAX_CHANGE) return { found: true, reached: f0, solution: x0, iterations: 1 }
        let x1 = x0 + Math.max(Math.abs(x0) * 0.01, 1), f1 = await evaluate(x1), iterations = 2
        while (iterations < MAX_ITERATIONS) {
          if (Math.abs(f1 - input.toValue) <= MAX_CHANGE) return { found: true, reached: f1, solution: x1, iterations }
          const slope = f1 - f0
          if (slope === 0 || !Number.isFinite(slope)) break
          const next = x1 - ((f1 - input.toValue) * (x1 - x0)) / slope
          if (!Number.isFinite(next)) break
          x0 = x1; f0 = f1; x1 = next; f1 = await evaluate(x1); iterations++
        }
        if (Math.abs(f1 - input.toValue) <= MAX_CHANGE) return { found: true, reached: f1, solution: x1, iterations }
        await restore()
        return { found: false, reached: f1, solution: x1, iterations }
      } catch (error) { await restore(); throw error }
      finally { running = false; cancel = undefined }
    },
  }
}
