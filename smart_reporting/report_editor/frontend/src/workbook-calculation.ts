/**
 * Formulas ▸ Formula Auditing / Calculation (fixed source GenOffice f8c17004
 * `calc-options.ts`, `formula-view.ts`, `ribbon-actions.ts:1067-1084`,
 * `App.tsx:4758-4774`).
 *
 * - Show Formulas is per-sheet view state persisted as sheetView/@showFormulas
 *   (the save diff compares it with the file through applyPageSetups). Univer's
 *   raw-formula render key only reaches rich-text cells, so a CELL_CONTENT
 *   interceptor swaps formula text in; the key is still flipped so skeletons
 *   drop their text cache and repaint.
 * - Calculation Options is editor state, as in the fixed source: Manual vetoes
 *   the engine's calculation kick-off until Calculate Now / Calculate Sheet.
 *   Recalculated values are calculation results, never saved as edits.
 */
import { CellValueType, CustomCommandExecutionError, ICommandService, IContextService } from '@univerjs/core'
import { INTERCEPTOR_POINT, SheetInterceptorService } from '@univerjs/sheets'

/** engine-render RENDER_RAW_FORMULA_KEY (kept literal: no runtime import of the render package here). */
export const RENDER_RAW_FORMULA_KEY = 'RENDER_RAW_FORMULA'
export const CALCULATION_START = 'formula.mutation.set-formula-calculation-start'
export const CALCULATION_TRIGGER = 'formula.mutation.set-trigger-formula-calculation-start'

type Injector = { get<T>(token: unknown): T }
export type CalculationRuntime = { univer: { __getInjector(): Injector } }

export interface CalculationControl {
  readonly manual: () => boolean
  setManual(manual: boolean): void
  /** F9: every formula in the workbook. */
  calculateNow(): void
  /** Shift+F9: every formula on the sheet (and dependents of its cells). */
  calculateSheet(sheet: { unitId: string; sheetId: string; sheetName: string; rows: number; columns: number }): void
  /** Formula view: re-sync the render key to the active sheet's flag. */
  syncFormulaView(on: boolean): void
  dispose(): void
}

export function installCalculation(runtime: CalculationRuntime, formulaView: (sheetId: string) => boolean): CalculationControl {
  const injector = runtime.univer.__getInjector()
  const commands = injector.get<ICommandService>(ICommandService)
  let manual = false, allowNext = false
  // Cancelling (not emptying) matters: an empty cycle still refreshes volatile functions.
  const veto = commands.beforeCommandExecuted(command => {
    if (command.id !== CALCULATION_START || !manual || allowNext) return
    if ((command.params as { forceCalculation?: boolean } | undefined)?.forceCalculation) return
    const stack = (commands as unknown as { _commandExecutionStack?: unknown[] })._commandExecutionStack
    const index = stack?.indexOf(command) ?? -1
    if (index >= 0) stack?.splice(index, 1)
    throw new CustomCommandExecutionError('manual calculation mode')
  })
  const interceptor = injector.get<SheetInterceptorService>(SheetInterceptorService).intercept(INTERCEPTOR_POINT.CELL_CONTENT, {
    // Above NUMFMT (10): a formula cell in formula view shows its text, not the formatted value.
    priority: 9999,
    handler: (cell, location, next) => {
      if (!formulaView(location.subUnitId)) return next(cell)
      const formula = (location.rawData as { f?: unknown } | undefined)?.f
      if (typeof formula !== 'string' || formula === '') return next(cell)
      return { ...(cell ?? {}), v: formula, t: CellValueType.STRING, p: null } as never
    },
  })
  const context = injector.get<IContextService>(IContextService)
  const calculateNow = () => { void commands.executeCommand(CALCULATION_TRIGGER, { commands: [], forceCalculation: true }, { onlyLocal: true }) }
  return {
    manual: () => manual,
    setManual(next) {
      manual = next
      // Excel recalculates when flipping back to automatic.
      if (!next) calculateNow()
    },
    calculateNow,
    calculateSheet({ unitId, sheetId, sheetName, rows, columns }) {
      allowNext = true
      try {
        commands.syncExecuteCommand(CALCULATION_START, {
          commands: [],
          dirtyRanges: [{ unitId, sheetId, range: { startRow: 0, endRow: Math.max(0, rows - 1), startColumn: 0, endColumn: Math.max(0, columns - 1) } }],
          dirtyNameMap: { [unitId]: { [sheetId]: sheetName } },
        })
      } finally { allowNext = false }
    },
    syncFormulaView(on) {
      if (Boolean(context.getContextValue(RENDER_RAW_FORMULA_KEY)) !== on) context.setContextValue(RENDER_RAW_FORMULA_KEY, on)
    },
    dispose() { veto.dispose(); interceptor.dispose() },
  }
}
