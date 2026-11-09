/// Univer runtime wiring: load a workbook model into the grid, push engine
/// edits back into it, and read the current grid state back for saving.
///
/// The facade is accessed through a local structural type: the dependency
/// tree contains a second pinned @univerjs/core copy (under @univerjs/rpc)
/// whose module augmentation does not attach to the copy we type against,
/// so the sheet-side methods are declared here instead.

import { parseRange, type CellEdit } from '@sheets-web/xlsx-engine'
import type { UniverStyleData } from '../core/style-map'
import { fromUniverStyle, univerBorderStyleId } from '../core/style-map'
import type { ReadbackWorkbook, ReadbackCell } from '../core/session-core'
import type { UniverWorkbookData } from '../core/univer-data'
import { engineCfToUniverRule, type UniverColumnData, type UniverRowData } from '../core/univer-data'
import { setSparklines } from './sparkline-render'
import { setCharts } from './chart-render'
import type { UniverRuntime } from './create-univer'

interface FacadeWorksheet {
  getName?(): string
  getSheetName?(): string
  getSheetBySheetId(id: string): FacadeWorksheet | null
  getActiveSheet(): FacadeWorksheet | null
  getSheets(): FacadeWorksheet[]
  getRange(address: string): FacadeRange
  getRange(row: number, column: number): FacadeRange
  setFrozenRows(rows: number): unknown
  setFrozenColumns(columns: number): unknown
  getMaxRows(): number
  getMaxColumns(): number
}

/// FRange surface used for live pushes, verified against the installed
/// @univerjs/sheets facade typings: there is no getName()/setStyle() there,
/// only getSheetName() and per-property style setters.
interface FacadeRange {
  setFormula(formula: string): unknown
  setValue(value: unknown): unknown
  getValue?(): unknown
  clearContent(): unknown
  setFontWeight(weight: 'bold' | 'normal'): unknown
  setFontStyle(style: 'italic' | 'normal'): unknown
  setFontLine(line: 'underline' | 'line-through' | 'none'): unknown
  setFontSize(size: number): unknown
  setFontFamily(family: string): unknown
  setFontColor(color: string): unknown
  setBackground(color: string): unknown
  setHorizontalAlignment(alignment: 'left' | 'center' | 'right' | 'justify'): unknown
  setVerticalAlignment(alignment: 'top' | 'middle' | 'bottom'): unknown
  setWrap(wrap: boolean): unknown
  setNumberFormat(pattern: string): unknown
  setBorder(type: 'top' | 'bottom' | 'left' | 'right', style: number, color?: string): unknown
}

interface FacadeWorkbook {
  getId(): string
  getSnapshot(): unknown
  getSheets(): FacadeWorksheet[]
  getActiveSheet(): FacadeWorksheet | null
  getSheetBySheetId(id: string): FacadeWorksheet | null
}

interface Facade {
  getActiveWorkbook(): FacadeWorkbook | null
  createWorkbook(data: unknown): FacadeWorkbook | null
  disposeUnit(id: string): void
  syncExecuteCommand?(id: string, params: unknown): unknown
}

const facadeOf = (runtime: UniverRuntime | null): Facade | null =>
  runtime ? (runtime.univerAPI as unknown as Facade) : null

/// The facade renamed getName → getSheetName across versions; accept both so
/// live pushes keep working under either dependency resolution.
const sheetNameOf = (sheet: FacadeWorksheet): string =>
  sheet.getName?.() ?? sheet.getSheetName?.() ?? ''

export function loadWorkbookData(runtime: UniverRuntime | null, data: UniverWorkbookData): void {
  const facade = facadeOf(runtime)
  if (!facade) return
  const active = facade.getActiveWorkbook()
  if (active) facade.disposeUnit(active.getId())
  // sparklines AND charts must be in their render extensions' stores BEFORE
  // the workbook is created, so the first paint already draws them (the
  // extensions read the stores at draw time; a post-load same-value poke does
  // not dirty anything). The store key uses data.id — the unit id the new
  // workbook will carry.
  for (const sheet of Object.values(data.sheets)) {
    setSparklines(data.id, sheet.id, sheet.sparklines)
    setCharts(data.id, sheet.id, sheet.charts)
  }
  facade.createWorkbook(data)

  const workbook = facade.getActiveWorkbook()
  // defined names go to the formula engine via its mutation, so grid formulas
  // like =SUM(SalesData) resolve; facade variance is non-fatal like freeze
  for (const entry of data.definedNames ?? []) {
    try {
      facade.syncExecuteCommand?.('formula.mutation.set-defined-name', {
        unitId: workbook?.getId(),
        id: `name-${entry.name}`,
        name: entry.name,
        formulaOrRefString: entry.refersTo,
      })
    } catch {
      // names are an enhancement: formulas referencing them may not resolve
    }
  }
  for (const sheet of Object.values(data.sheets)) {
    const worksheet = workbook?.getSheetBySheetId(sheet.id)
    if (!worksheet) continue
    const freeze = data.freeze?.[sheet.id]
    if (freeze) {
      try {
        if (freeze.frozenRows > 0) worksheet.setFrozenRows(freeze.frozenRows)
        if (freeze.frozenColumns > 0) worksheet.setFrozenColumns(freeze.frozenColumns)
      } catch {
        // freeze facade variance across versions: non-fatal, the grid still loads
      }
    }
    // conditional formats: engine rules → Univer rules, then the CF preset
    // renders them. Facade variance is non-fatal like freeze above.
    for (const [index, engineRule] of (sheet.cfRules ?? []).entries()) {
      const rule = engineCfToUniverRule(engineRule, `cf-${sheet.id}-${index}`)
      if (!rule) continue
      try {
        ;(worksheet as unknown as {
          addConditionalFormattingRule?: (rule: unknown) => unknown
        }).addConditionalFormattingRule?.(rule)
        // The CF view model computes render data lazily per cell and only
        // invalidates on SetRangeValuesMutation; a rule added post-load would
        // never paint. Rewriting every covered cell's current value through
        // one values mutation marks the rule dirty with no undo entry and no
        // grid diff (capped, CF ranges are display rules not data).
        const cellValue: Record<number, Record<number, { v: unknown }>> = {}
        let poked = 0
        for (const range of rule.ranges) {
          for (let row = range.startRow; row <= range.endRow && poked < 200; row += 1) {
            for (
              let column = range.startColumn;
              column <= range.endColumn && poked < 200;
              column += 1
            ) {
              const current = worksheet.getRange(row, column).getValue?.() ?? null
              ;(cellValue[row] ??= {})[column] = { v: current }
              poked += 1
            }
          }
        }
        if (poked > 0) {
          facade.syncExecuteCommand?.('sheet.mutation.set-range-values', {
            unitId: workbook?.getId(),
            subUnitId: sheet.id,
            cellValue,
          })
        }
      } catch {
        // CF facade variance: the grid still loads without the highlight
      }
    }
  }
}

const columnLetters = (index: number): string => {
  let label = ''
  let remaining = index + 1
  while (remaining > 0) {
    remaining -= 1
    label = String.fromCharCode(65 + (remaining % 26)) + label
    remaining = Math.floor(remaining / 26)
  }
  return label
}

/// Grid → ReadbackWorkbook (values, formulas, logical styles).
export function readBack(runtime: UniverRuntime | null): ReadbackWorkbook {
  const empty: ReadbackWorkbook = { sheets: [] }
  const workbook = facadeOf(runtime)?.getActiveWorkbook()
  if (!workbook) return empty
  return readBackSnapshot(workbook.getSnapshot())
}

/** Shared projection for save capture and preflight of official replacement payloads. */
export function readBackSnapshot(data: unknown): ReadbackWorkbook {
  const snapshot = data as {
    sheets?: Record<string, {
      name?: string
      cellData?: Record<number, Record<number, { v?: unknown; f?: string; s?: string } | undefined>>
      mergeData?: Array<{ startRow: number; startColumn: number; endRow: number; endColumn: number }>
      columnData?: Record<string, UniverColumnData | undefined>
      rowData?: Record<string, UniverRowData | undefined>
    }>
    sheetOrder?: string[]
    styles?: Record<string, UniverStyleData>
  }
  const styles = snapshot.styles ?? {}
  const order = snapshot.sheetOrder ?? Object.keys(snapshot.sheets ?? {})
  const sheets = order.flatMap((sheetId) => {
    const sheet = snapshot.sheets?.[sheetId]
    if (!sheet?.name) return []
    const cells: Record<string, ReadbackCell> = {}
    for (const [rowKey, row] of Object.entries(sheet.cellData ?? {})) {
      for (const [columnKey, cell] of Object.entries(row ?? {})) {
        if (cell === undefined) continue
        const address = `${columnLetters(Number(columnKey))}${Number(rowKey) + 1}`
        const formula = typeof cell.f === 'string' && cell.f ? cell.f : undefined
        const rawValue = cell.v
        const value =
          rawValue === null || rawValue === undefined
            ? null
            : typeof rawValue === 'number' || typeof rawValue === 'boolean'
              ? rawValue
              : String(rawValue)
        const style = cell.s !== undefined ? fromUniverStyle(styles[cell.s] ?? {}) : undefined
        cells[address] = {
          value,
          ...(formula !== undefined ? { formula } : {}),
          ...(style !== undefined && Object.keys(style).length > 0 ? { style } : {}),
        }
      }
    }
    const merges = (sheet.mergeData ?? [])
      .filter((merge) =>
        Number.isSafeInteger(merge.startRow) && Number.isSafeInteger(merge.startColumn) &&
        merge.endRow >= merge.startRow && merge.endColumn >= merge.startColumn,
      )
      .map((merge) => ({
        startRow: merge.startRow,
        startColumn: merge.startColumn,
        endRow: merge.endRow,
        endColumn: merge.endColumn,
      }))
    const columnWidths: Record<number, number | undefined> = {}
    for (const [columnKey, column] of Object.entries(sheet.columnData ?? {})) {
      if (column?.w !== undefined) columnWidths[Number(columnKey)] = column.w
    }
    const rowHeights: Record<number, number | undefined> = {}
    const autoHeightRows: number[] = []
    for (const [rowKey, row] of Object.entries(sheet.rowData ?? {})) {
      if (row?.ia === 1) autoHeightRows.push(Number(rowKey))
      else if (row?.h !== undefined) rowHeights[Number(rowKey)] = row.h
    }
    return [{
      name: sheet.name,
      cells,
      ...(merges.length > 0 ? { merges } : {}),
      ...(Object.keys(columnWidths).length > 0 ? { columnWidths } : {}),
      ...(Object.keys(rowHeights).length > 0 ? { rowHeights } : {}),
      ...(autoHeightRows.length > 0 ? { autoHeightRows } : {}),
    }]
  })
  return { sheets }
}

/// WorkbookStyleEdit subset → individual FRange style setters. The facade has
/// no setStyle(row, column, IStyleData); every property maps to its own
/// method (signatures taken from the installed @univerjs/sheets typings).
function applyStyleToRange(range: FacadeRange, edit: NonNullable<CellEdit['style']>): void {
  if (edit.bold !== undefined) range.setFontWeight(edit.bold ? 'bold' : 'normal')
  if (edit.italic !== undefined) range.setFontStyle(edit.italic ? 'italic' : 'normal')
  if (edit.underline !== undefined || edit.strikethrough !== undefined) {
    range.setFontLine(edit.underline ? 'underline' : edit.strikethrough ? 'line-through' : 'none')
  }
  if (edit.fontSize !== undefined) range.setFontSize(edit.fontSize)
  if (edit.fontFamily !== undefined) range.setFontFamily(edit.fontFamily)
  if (typeof edit.fontColor === 'string') range.setFontColor(edit.fontColor)
  if (typeof edit.fillColor === 'string') range.setBackground(edit.fillColor)
  if (edit.horizontalAlignment !== undefined) {
    range.setHorizontalAlignment(
      edit.horizontalAlignment === 'distributed' ? 'justify' : edit.horizontalAlignment,
    )
  }
  if (edit.verticalAlignment !== undefined) {
    range.setVerticalAlignment(
      edit.verticalAlignment === 'center' ? 'middle' : edit.verticalAlignment,
    )
  }
  if (edit.wrapText !== undefined) range.setWrap(edit.wrapText)
  if (edit.numberFormat !== undefined) range.setNumberFormat(edit.numberFormat)
  const border = (edge: typeof edit.borderTop, type: 'top' | 'bottom' | 'left' | 'right'): void => {
    if (edge === undefined) return
    if (edge === null) {
      range.setBorder(type, 0)
      return
    }
    const id = univerBorderStyleId(edge.style)
    if (id !== undefined) {
      range.setBorder(type, id, typeof edge.color === 'string' ? edge.color : undefined)
    }
  }
  border(edit.borderTop, 'top')
  border(edit.borderBottom, 'bottom')
  border(edit.borderLeft, 'left')
  border(edit.borderRight, 'right')
}

/// Push engine edits into the grid so AI operations appear live.
export function pushEdits(runtime: UniverRuntime | null, edits: readonly CellEdit[]): void {
  const workbook = facadeOf(runtime)?.getActiveWorkbook()
  if (!workbook) return
  const worksheets = new Map(
    workbook.getSheets().map((sheet) => [sheetNameOf(sheet), sheet]),
  )
  for (const edit of edits) {
    const worksheet = worksheets.get(edit.sheetName)
    if (!worksheet) continue
    const address = `${columnLetters(edit.column)}${edit.row + 1}`
    try {
      const range = worksheet.getRange(address)
      if (edit.writeValue) {
        if (edit.cell.formula) range.setFormula(edit.cell.formula)
        else if (edit.cell.value === null) range.clearContent()
        else range.setValue(edit.cell.value)
      }
      if (edit.style) applyStyleToRange(range, edit.style)
    } catch {
      // facade variance across versions: skip the cell rather than abort the batch
    }
  }
}

/// Number of rows/columns of a sheet (for write guards).
export function gridBounds(
  runtime: UniverRuntime | null,
): { maxRow: number; maxColumn: number } {
  const worksheet = facadeOf(runtime)?.getActiveWorkbook()?.getActiveSheet()
  if (!worksheet) return { maxRow: 1000, maxColumn: 26 }
  return {
    maxRow: worksheet.getMaxRows(),
    maxColumn: worksheet.getMaxColumns(),
  }
}

/// Name of the currently active sheet (export targets it).
export function activeSheetName(runtime: UniverRuntime | null): string | undefined {
  const sheet = facadeOf(runtime)?.getActiveWorkbook()?.getActiveSheet()
  return sheet ? sheetNameOf(sheet) : undefined
}

/// Opens Univer's find / find-replace panel by executing the operation the
/// preset's own Ctrl+F / Ctrl+H shortcuts run (@univerjs/find-replace
/// `ui.operation.open-find-dialog` / `open-replace-dialog`). The operation's
/// handler calls findReplaceService.start(), which lazily initializes the
/// provider controller, so the panel appears on first use.
export async function openFindReplace(runtime: UniverRuntime | null, replace: boolean): Promise<void> {
  if (!runtime) throw new Error('工作簿尚未就绪')
  const operation = replace ? 'ui.operation.open-replace-dialog' : 'ui.operation.open-find-dialog'
  if (!await runtime.univerAPI.executeCommand(operation)) throw new Error('查找/替换面板未能打开，请重试')
}
