import { CellValueType, isDefaultFormat, Range } from '@univerjs/core'
import { INumfmtService, SheetsSelectionsService } from '@univerjs/sheets'
import { getDecimalFromPattern, setPatternDecimal } from '@univerjs/sheets-numfmt'
import type { UniverRuntime } from './create-univer'

interface CellValue { row: number; col: number; pattern: string }
interface RawCell { v?: unknown; t?: unknown }

function rawValueDecimals(cell: RawCell | null): number {
  if (!cell || cell.t !== CellValueType.NUMBER || !cell.v) return 0
  return /\.(\d*)$/.exec(String(cell.v))?.[1]?.length ?? 0
}

export function stepSelectionDecimals(runtime: UniverRuntime, step: 1 | -1): void {
  const injector = runtime.univer.__getInjector()
  const selections = injector.get(SheetsSelectionsService).getCurrentSelections()
  const numfmt = injector.get(INumfmtService)
  const workbook = runtime.univerAPI.getActiveWorkbook()
  const sheet = workbook?.getActiveSheet()
  if (!workbook || !sheet || !selections?.length) return
  const unitId = workbook.getId()
  const subUnitId = sheet.getSheetId()
  const worksheet = sheet.getSheet()
  const currentPattern = (row: number, col: number): string | null => {
    const value = numfmt.getValue(unitId, subUnitId, row, col)
    return value && !isDefaultFormat(value.pattern) ? value.pattern : null
  }

  let maxDecimals = 0
  for (const selection of selections) {
    Range.foreach(selection.range, (row, col) => {
      const pattern = currentPattern(row, col)
      if (!pattern && !maxDecimals) {
        const decimals = rawValueDecimals(worksheet.getCellRaw(row, col) as RawCell | null)
        if (decimals) maxDecimals = decimals
      } else if (pattern) maxDecimals = Math.max(maxDecimals, getDecimalFromPattern(pattern))
    })
  }

  const decimals = maxDecimals + step
  const fallback = setPatternDecimal(`0${decimals > 0 ? '.0' : step < 0 ? '.' : ''}`, Math.max(0, decimals))
  const values: CellValue[] = []
  for (const selection of selections) {
    Range.foreach(selection.range, (row, col) => {
      const pattern = currentPattern(row, col)
      if (!pattern) {
        values.push({ row, col, pattern: fallback })
        return
      }
      const next = setPatternDecimal(pattern, Math.max(0, getDecimalFromPattern(pattern) + step))
      if (step < 0 || next !== pattern) values.push({ row, col, pattern: next })
    })
  }
  if (values.length) {
    void runtime.univerAPI.executeCommand('sheet.command.numfmt.set.numfmt', { unitId, subUnitId, values })
  }
}
