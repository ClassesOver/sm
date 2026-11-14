/// Workbook model → Univer workbook data (pure; DOM-free so it is testable
/// in node). Rebuilt from genoffice's loadSnapshotIntoUniver data shape with
/// styles carried through the workbook styles map instead of post-load
/// facade calls.

import {
  columnIndex,
  parseAddress,
  parseRange,
  type ChartReadSpec,
  type CfReadableRule,
  type ModelCell,
  type SparklineSpec,
  type WorkbookModel,
} from '@sheets-web/xlsx-engine'
import { CellValueType } from '@univerjs/core'
import { logicalStyleOf, toUniverStyle, type LogicalStyle } from './style-map'
import {columnWidthToPixels,rowHeightToPixels} from '@sheets-web/xlsx-engine/geometry'
export {columnWidthToPixels,rowHeightToPixels} from '@sheets-web/xlsx-engine/geometry'

export const MINIMUM_SHEET_ROW_COUNT = 1000
export const MINIMUM_SHEET_COLUMN_COUNT = 26

export interface UniverCellData {
  v?: string | number | boolean | undefined
  /// Univer cell value type marker (CellValueType); grid features like the
  /// official sort branch on it, so the projection always sets it for values.
  t?: number | undefined
  f?: string | undefined
  /// style map key ('' when the cell has no style)
  s?: string | undefined
}

export interface UniverSheetData {
  id: string
  name: string
  hidden?: 1
  custom?: Record<string, unknown>
  rowCount: number
  columnCount: number
  defaultColumnWidth: number
  defaultRowHeight: number
  cellData: Record<number, Record<number, UniverCellData>>
  mergeData?: Array<{ startRow: number; startColumn: number; endRow: number; endColumn: number }>
  columnData?: Record<number, UniverColumnData>
  rowData?: Record<number, UniverRowData>
  /// engine CF rules the loader feeds to Univer's conditional formatting
  cfRules?: ReadonlyArray<CfReadableRule>
  /// sparkline specs the render extension draws (x14, read back for display)
  sparklines?: ReadonlyArray<SparklineSpec>
  /// anchored chart specs the render extension draws (column/bar/line/pie v1)
  charts?: ReadonlyArray<ChartReadSpec>
}

/// Univer 0.25.1 IColumnData / IRowData keys: width `w` and height `h` in
/// pixels, hidden `hd` as BooleanNumber (1 = hidden). The sheets-web snapshot
/// this file was migrated from wrote `width`/`height`/`hidden`, which Univer
/// ignores — file geometry was not shown and grid resizes/hides never reached
/// the save diff. GenOffice f8c17004 univer-sync.ts uses these real keys.
export interface UniverColumnData { custom?: Record<string, unknown>; w?: number | undefined; hd?: number | undefined }
export interface UniverRowData { custom?: Record<string, unknown>; h?: number | undefined; ia?: number | undefined; ah?: number | undefined; hd?: number | undefined }
export const isHiddenAxisEntry = (entry: { hd?: number | undefined } | null | undefined): boolean => entry?.hd === 1

export interface UniverWorkbookData {
  id: string
  name: string
  sheetOrder: string[]
  sheets: Record<string, UniverSheetData>
  /// styleId → Univer style entry
  styles: Record<string, ReturnType<typeof toUniverStyle>>
  freeze?: Record<string, { frozenRows: number; frozenColumns: number }>
  /// workbook-level defined names; the loader registers them with the formula
  /// engine so grid formulas can reference them
  definedNames?: ReadonlyArray<{ name: string; refersTo: string; scopeSheetId?: string | undefined }>
}
export function buildWorkbookData(
  model: WorkbookModel,
  workbookId: string,
  workbookName: string,
): UniverWorkbookData {
  const styles: UniverWorkbookData['styles'] = {}
  const styleKeys = new Map<string, string>()
  const styleIdFor = (style: LogicalStyle | undefined): string | undefined => {
    if (style === undefined) return undefined
    const json = JSON.stringify(toUniverStyle(style))
    const existing = styleKeys.get(json)
    if (existing !== undefined) return existing
    const id = `s${styleKeys.size}`
    styleKeys.set(json, id)
    styles[id] = toUniverStyle(style)
    return id
  }

  const sheets: Record<string, UniverSheetData> = {}
  const sheetOrder: string[] = []
  const freeze: UniverWorkbookData['freeze'] = {}
  model.sheets.forEach((sheet, sheetIndex) => {
    const id = `sheet-${sheetIndex}`
    sheetOrder.push(id)
    const cellData: UniverSheetData['cellData'] = {}
    let maximumRow = 0
    let maximumColumn = 0
    for (const [address, cell] of Object.entries(sheet.cells)) {
      const coordinates = parseAddress(address)
      maximumRow = Math.max(maximumRow, coordinates.row)
      maximumColumn = Math.max(maximumColumn, coordinates.column)
      const logical =
        cell.styleIndex === undefined
          ? undefined
          : logicalStyleOf(model.styles, model.styles.cellXfs[cell.styleIndex], model.themePalette)
      const rowData = cellData[coordinates.row] ?? {}
      rowData[coordinates.column] = univerCellOf(cell, styleIdFor(logical))
      cellData[coordinates.row] = rowData
    }
    const merges = sheet.merges
      .map((reference) => {
        const bounds = reference.split(':')
        const start = parseAddress(bounds[0] ?? reference)
        const end = bounds[1] === undefined ? start : parseAddress(bounds[1])
        return {
          startRow: Math.min(start.row, end.row),
          startColumn: Math.min(start.column, end.column),
          endRow: Math.max(start.row, end.row),
          endColumn: Math.max(start.column, end.column),
        }
      })
      .filter((merge) => merge.endRow >= merge.startRow && merge.endColumn >= merge.startColumn)
    const columnData: UniverSheetData['columnData'] = {}
    for (const column of sheet.columns) {
      if (column.width === undefined && !column.hidden && !column.outlineLevel && !column.collapsed) continue
      if (column.outlineLevel || column.collapsed || column.hidden) maximumColumn = Math.max(maximumColumn, column.end - 1)
      for (let index = column.start - 1; index < column.end && index < 16384; index += 1) {
        columnData[index] = {
          ...(column.width !== undefined ? { w: columnWidthToPixels(column.width) } : {}),
          ...(column.hidden ? { hd: 1 } : {}),
          custom: { genofficeOutline: {level: column.outlineLevel ?? 0, collapsed: column.collapsed ?? false} },
        }
      }
    }
    const rowData: UniverSheetData['rowData'] = {}
    for (const row of sheet.rows) {
      if (row.height === undefined && !row.hidden && !row.outlineLevel && !row.collapsed) continue
      if (row.outlineLevel || row.collapsed || row.hidden) maximumRow = Math.max(maximumRow, row.row - 1)
      rowData[row.row - 1] = {
        // file heights are explicit (Excel customHeight): ia 0, as setRowHeightsForced writes,
        // so AutoFit Row Height (ia 1) is distinguishable from an untouched row
        ...(row.height !== undefined ? { h: rowHeightToPixels(row.height), ia: 0 } : {}),
        ...(row.hidden ? { hd: 1 } : {}),
        custom: { genofficeOutline: {level: row.outlineLevel ?? 0, collapsed: row.collapsed ?? false} },
      }
    }
    if (sheet.freeze && (sheet.freeze.frozenRows > 0 || sheet.freeze.frozenColumns > 0)) {
      freeze![id] = sheet.freeze
    }
    sheets[id] = {
      id,
      name: sheet.name,
      ...(sheet.hidden ? { hidden: 1 as const } : {}),
      custom: {genofficeOutline: {summaryBelow: sheet.outlineSummaryBelow ?? true, summaryRight: sheet.outlineSummaryRight ?? true}},
      rowCount: Math.min(1048576, Math.max(MINIMUM_SHEET_ROW_COUNT, maximumRow + 100)),
      columnCount: Math.min(16384, Math.max(MINIMUM_SHEET_COLUMN_COUNT, maximumColumn + 10)),
      defaultColumnWidth: sheet.defaultColumnWidthPx ?? columnWidthToPixels(8.43),
      defaultRowHeight: sheet.defaultRowHeightPx ?? rowHeightToPixels(15),
      cellData,
      ...(merges.length > 0 ? { mergeData: merges } : {}),
      ...(Object.keys(columnData).length > 0 ? { columnData } : {}),
      ...(Object.keys(rowData).length > 0 ? { rowData } : {}),
      ...(sheet.conditionalFormats !== undefined && sheet.conditionalFormats.length > 0
        ? { cfRules: sheet.conditionalFormats }
        : {}),
      ...(sheet.sparklines !== undefined && sheet.sparklines.length > 0
        ? { sparklines: sheet.sparklines }
        : {}),
      ...(sheet.charts !== undefined && sheet.charts.length > 0
        ? { charts: sheet.charts }
        : {}),
    }
  })

  return {
    id: workbookId,
    name: workbookName,
    sheetOrder,
    sheets,
    styles,
    ...(freeze !== undefined && Object.keys(freeze).length > 0 ? { freeze } : {}),
    ...(model.definedNames !== undefined && model.definedNames.length > 0
      ? { definedNames: model.definedNames.map(entry => ({ name: entry.name, refersTo: entry.refersTo, ...(entry.scopeSheetName !== undefined ? { scopeSheetId: sheetOrder[model.sheets.findIndex(sheet => sheet.name === entry.scopeSheetName)] } : {}) })) }
      : {}),
  }
}

function univerCellOf(cell: ModelCell, styleId: string | undefined): UniverCellData {
  if (cell.formula) return { f: cell.formula, ...(styleId !== undefined ? { s: styleId } : {}) }
  if (cell.value === null || cell.value === undefined) {
    return styleId === undefined ? {} : { s: styleId }
  }
  // Univer features (official sort, statistic bar) branch on the cell type
  // marker; without `t` numbers compare as strings and sort lexicographically.
  const valueType = typeof cell.value === 'number' ? CellValueType.NUMBER
    : typeof cell.value === 'boolean' ? CellValueType.BOOLEAN : CellValueType.STRING
  return { v: cell.value, t: valueType, ...(styleId !== undefined ? { s: styleId } : {}) }
}

/// A1 → Univer (row, column) helper for the sync layer.
export function cellCoordinates(address: string): { row: number; column: number } {
  return parseAddress(address)
}

export { columnIndex }

/// sqref ("B2:B4 C1:C2") → Univer ranges (0-based, inclusive).
function rangesOfSqref(sqref: string): Array<{
  startRow: number
  startColumn: number
  endRow: number
  endColumn: number
}> {
  const ranges: Array<{
    startRow: number
    startColumn: number
    endRow: number
    endColumn: number
  }> = []
  for (const token of sqref.split(/\s+/).filter(Boolean)) {
    try {
      const bounds = parseRange(token)
      ranges.push({
        startRow: bounds.startRow,
        startColumn: bounds.startColumn,
        endRow: bounds.endRow,
        endColumn: bounds.endColumn,
      })
    } catch {
      // skip unparseable tokens rather than dropping the whole rule
    }
  }
  return ranges
}

function cfvoToValueConfig(threshold: {
  type: string
  value?: number | string | undefined
}): { type: string; value?: number | string | undefined } {
  return {
    type: threshold.type,
    ...(threshold.value !== undefined ? { value: threshold.value } : {}),
  }
}

export interface UniverCfRule {
  ranges: Array<{ startRow: number; startColumn: number; endRow: number; endColumn: number }>
  cfId: string
  stopIfTrue: boolean
  rule:
    | {
        type: 'dataBar'
        isShowValue: boolean
        config: {
          min: { type: string; value?: number | string | undefined }
          max: { type: string; value?: number | string | undefined }
          isGradient: boolean
          positiveColor: string
          nativeColor: string
        }
      }
    | {
        type: 'colorScale'
        config: Array<{
          index: number
          color: string
          value: { type: string; value?: number | string | undefined }
        }>
      }
}

/// Engine CF rule → Univer IConditionFormattingRule shape. cellIs and iconSet
/// are write-only boundaries and return null (documented in the engine).
export function engineCfToUniverRule(rule: CfReadableRule, cfId: string): UniverCfRule | null {
  const ranges = rangesOfSqref(rule.sqref)
  if (ranges.length === 0) return null
  if (rule.kind === 'dataBar') {
    return {
      ranges,
      cfId,
      stopIfTrue: rule.stopIfTrue ?? false,
      rule: {
        type: 'dataBar',
        isShowValue: rule.showValue !== false,
        config: {
          min: cfvoToValueConfig(rule.min),
          max: cfvoToValueConfig(rule.max),
          isGradient: true,
          positiveColor: rule.color,
          nativeColor: rule.color,
        },
      },
    }
  }
  if (rule.kind === 'colorScale') {
    return {
      ranges,
      cfId,
      stopIfTrue: rule.stopIfTrue ?? false,
      rule: {
        type: 'colorScale',
        config: rule.stops.map((stop, index) => ({
          index,
          color: stop.color,
          value: cfvoToValueConfig(stop.cfvo),
        })),
      },
    }
  }
  return null
}
