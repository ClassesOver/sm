/// Session core (DOM-free): diffing the grid read-back against the imported
/// model into engine CellEdits, plus the AI write-operation schema with
/// preview/apply/undo semantics. The safety model mirrors the desktop app:
/// AI output is untrusted, schema-validated, previewed, then applied through
/// the same single write path a save uses.

import { z } from 'zod'

import {
  applyFlashFillTemplate,
  columnIndex,
  computeSortChanges,
  conditionalFormatWireRuleSchema,
  isValidRuleSqref,
  formatAddress,
  inferFlashFillTemplate,
  parseAddress,
  parseRange,
  rangeCellCount,
  rangeAddresses,
  workbookStyleEditSchema,
  type Cfvo,
  type CfWireRule,
  type CellEdit,
  type FlashFillExample,
  type ModelCell,
  type WorkbookModel,
} from '@sheets-web/xlsx-engine'
import { logicalStyleOf } from './style-map'
import { styleDelta, type LogicalStyle } from './style-map'
import { textToColumnChanges } from './data-tools'

/// What the sync layer reads back from the grid for one cell.
export interface ReadbackCell {
  value: string | number | boolean | null
  formula?: string | undefined
  style?: LogicalStyle | undefined
}

export interface ReadbackSheet {
  name: string
  cells: Record<string, ReadbackCell>
  /// worksheet merges in 0-based inclusive bounds (from the Univer snapshot),
  /// used by save and print; undefined for grids that expose none
  merges?: ReadonlyArray<{
    startRow: number
    startColumn: number
    endRow: number
    endColumn: number
  }>
  /// per-column pixel widths keyed by 0-based column index (print layout)
  columnWidths?: Readonly<Record<number, number | undefined>>
  /// per-row pixel heights keyed by 0-based row index (geometry persistence)
  rowHeights?: Readonly<Record<number, number | undefined>>
  /// rows the grid sizes automatically (Univer rowData.ia = 1), e.g. after AutoFit Row Height
  autoHeightRows?: readonly number[]
}

export interface ReadbackWorkbook {
  sheets: ReadbackSheet[]
}

const CELL_REF = /^[A-Z]{1,3}[1-9][0-9]{0,6}$/

/// Structural (insert/delete rows/columns) and sheet-management requests.
/// These bypass the value-level edit pipeline: the caller applies them to the
/// package bytes directly and reloads the workbook.
export const structuralOpsSchema = z
  .object({
    /// 1-based row/column number the insert/delete starts at (Excel semantics)
    insertRows: z.array(z.object({ at: z.number().int().min(1).max(1048576), count: z.number().int().min(1).max(1000) }).strict()).max(20).optional(),
    deleteRows: z.array(z.object({ at: z.number().int().min(1).max(1048576), count: z.number().int().min(1).max(1000) }).strict()).max(20).optional(),
    insertColumns: z.array(z.object({ at: z.number().int().min(1).max(16384), count: z.number().int().min(1).max(200) }).strict()).max(20).optional(),
    deleteColumns: z.array(z.object({ at: z.number().int().min(1).max(16384), count: z.number().int().min(1).max(200) }).strict()).max(20).optional(),
  })
  .strict()

export type StructuralOps = z.infer<typeof structuralOpsSchema>

export const sheetOpsSchema = z
  .object({
    renameSheet: z.array(z.object({ sheet: z.string().min(1).max(64), newName: z.string().min(1).max(31) }).strict()).max(10).optional(),
    addSheet: z.array(z.object({ name: z.string().min(1).max(31) }).strict()).max(10).optional(),
    deleteSheet: z.array(z.object({ sheet: z.string().min(1).max(64) }).strict()).max(10).optional(),
  })
  .strict()

export type SheetOps = z.infer<typeof sheetOpsSchema>

const SQREF = /^\$?[A-Z]{1,3}\$?[0-9]{1,7}(:\$?[A-Z]{1,3}\$?[0-9]{1,7})?( \$?[A-Z]{1,3}\$?[0-9]{1,7}(:\$?[A-Z]{1,3}\$?[0-9]{1,7})?)*$/
const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/

export const ruleOpsSchema = z
  .object({
    setDataValidations: z
      .array(
        z
          .object({
            sheet: z.string().min(1).max(64),
            sqref: z.string().regex(SQREF),
            type: z.enum(['whole', 'decimal', 'list', 'date', 'textLength']),
            operator: z
              .enum(['between', 'notBetween', 'equal', 'notEqual', 'greaterThan', 'lessThan', 'greaterThanOrEqual', 'lessThanOrEqual'])
              .optional(),
            formula1: z.string().max(500).optional(),
            formula2: z.string().max(500).optional(),
            promptTitle: z.string().max(64).optional(),
            prompt: z.string().max(255).optional(),
            errorTitle: z.string().max(64).optional(),
            error: z.string().max(255).optional(),
          })
          .strict(),
      )
      .max(20)
      .optional(),
    setConditionalFormats: z.array(conditionalFormatWireRuleSchema).max(20).optional(),
    editCharts: z
      .array(
        z
          .object({
            /// chart number in the workbook's chart list (1-based)
            chart: z.number().int().min(1).max(64),
            title: z.string().min(1).max(120).optional(),
            chartType: z.enum(['column', 'bar', 'line', 'area', 'pie', 'doughnut']).optional(),
            /// series index (0-based, document order) → #RRGGBB
            seriesColors: z.record(z.string().regex(/^[0-9]{1,2}$/), z.string().regex(HEX_COLOR)).optional(),
            legend: z.enum(['none', 'right', 'bottom', 'top', 'left']).optional(),
            dataLabels: z.enum(['none', 'value', 'percent', 'category-percent']).optional(),
            dataLabelPosition: z.enum(['center', 'inside-end', 'outside-end']).optional(),
            dataLabelFormat: z.string().min(1).max(64).optional(),
            axisTitles: z
              .object({
                category: z.string().min(1).max(120).nullable().optional(),
                value: z.string().min(1).max(120).nullable().optional(),
              })
              .strict()
              .refine((titles) => titles.category !== undefined || titles.value !== undefined, {
                message: 'An axis-titles edit needs category or value.',
              })
              .optional(),
            pointColors: z
              .record(
                z.string().regex(/^[0-9]{1,2}$/),
                z.record(z.string().regex(/^[0-9]{1,2}$/), z.string().regex(HEX_COLOR)),
              )
              .optional(),
            grouping: z.enum(['clustered', 'stacked', 'percentStacked']).optional(),
            gridlines: z.boolean().optional(),
            valueAxis: z
              .object({
                min: z.number().finite().nullable().optional(),
                max: z.number().finite().nullable().optional(),
              })
              .strict()
              .refine((axis) => axis.min !== undefined || axis.max !== undefined, {
                message: 'A value-axis edit needs min or max.',
              })
              .optional(),
            gapWidthPct: z.number().int().min(0).max(500).optional(),
            holeSizePct: z.number().int().min(10).max(90).optional(),
            explosionPct: z.number().int().min(0).max(400).optional(),
            pointExplosions: z
              .record(z.string().regex(/^[0-9]{1,2}$/), z.number().int().min(0).max(400))
              .optional(),
            seriesSet: z
              .array(
                z
                  .object({
                    name: z.string().min(1).max(120),
                    values: z.array(z.number().finite()).min(1).max(1000),
                    valuesRef: z.string().min(1).max(512).optional(),
                    categories: z.array(z.string().max(120)).max(1000).optional(),
                    categoriesRef: z.string().min(1).max(512).optional(),
                    color: z.string().regex(HEX_COLOR).optional(),
                    plot: z.enum(['barChart', 'lineChart']).optional(),
                    secondaryAxis: z.boolean().optional(),
                  })
                  .strict(),
              )
              .min(1)
              .max(24)
              .optional(),
            series: z
              .array(
                z
                  .object({
                    index: z.number().int().min(0).max(63),
                    name: z.string().min(1).max(120).optional(),
                    values: z.array(z.number().finite()).min(1).max(1000).optional(),
                    valuesRef: z.string().min(1).max(512).optional(),
                    categories: z.array(z.string().max(120)).max(1000).optional(),
                    categoriesRef: z.string().min(1).max(512).optional(),
                  })
                  .strict()
                  .refine(
                    (entry) =>
                      entry.name !== undefined ||
                      entry.values !== undefined ||
                      entry.categories !== undefined,
                    { message: 'A series edit needs a name, values, or categories.' },
                  ),
              )
              .max(24)
              .optional(),
          })
          .strict()
          .refine(
            (edit) =>
              edit.title !== undefined ||
              edit.chartType !== undefined ||
              edit.seriesColors !== undefined ||
              edit.legend !== undefined ||
              edit.dataLabels !== undefined ||
              edit.dataLabelPosition !== undefined ||
              edit.dataLabelFormat !== undefined ||
              edit.axisTitles !== undefined ||
              edit.pointColors !== undefined ||
              edit.grouping !== undefined ||
              edit.gridlines !== undefined ||
              edit.valueAxis !== undefined ||
              edit.gapWidthPct !== undefined ||
              edit.holeSizePct !== undefined ||
              edit.explosionPct !== undefined ||
              edit.pointExplosions !== undefined ||
              edit.seriesSet !== undefined ||
              edit.series !== undefined,
            { message: 'A chart edit needs at least one change.' },
          ),
      )
      .max(10)
      .optional(),
    /// Creates brand-new chart parts from a data range (series extracted like
    /// recommendCharts; refs link the chart to the source cells).
    addCharts: z
      .array(
        z
          .object({
            sheet: z.string().min(1).max(64).optional(),
            chartType: z.enum([
              'column',
              'bar',
              'line',
              'area',
              'pie',
              'scatter',
              'radar',
              'doughnut',
              'combo',
            ]),
            dataRange: z.string().min(2).max(64),
            title: z.string().min(1).max(120).optional(),
            anchorCell: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/).optional(),
          })
          .strict(),
      )
      .max(5)
      .optional(),
    /// Replaces the full comment set of a sheet; notes: [] removes them all.
    setNotes: z
      .array(
        z
          .object({
            sheet: z.string().min(1).max(64),
            notes: z
              .array(
                z
                  .object({
                    cell: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/),
                    author: z.string().min(1).max(64),
                    text: z.string().min(1).max(2000),
                  })
                  .strict(),
              )
              .max(200),
          })
          .strict(),
      )
      .max(10)
      .optional(),
    /// Creates one pivot table (1-3 row levels, 0-2 column levels, 1-8 value
    /// fields). Field names must match the source header row; members are
    /// deduplicated from the source data in encounter order.
    addPivot: z
      .array(
        z
          .object({
            name: z.string().min(1).max(64),
            sourceSheet: z.string().min(1).max(64),
            /// source data area including the header row, e.g. "A1:C10"
            sourceRange: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$/),
            /// top-left of the baked output (Excel recalculates the extent)
            targetCell: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/),
            /// row dimension field names, outer level first
            rowFields: z.array(z.string().min(1).max(128)).min(1).max(3),
            /// column dimension field names, outer level first
            columnFields: z.array(z.string().min(1).max(128)).max(2).optional(),
            values: z
              .array(
                z
                  .object({
                    /// source field name; omit when formula is present
                    field: z.string().min(1).max(128).optional(),
                    agg: z.enum(['sum', 'count', 'average', 'max', 'min']),
                    numFmt: z.string().max(64).optional(),
                    /// "show values as" percent modes (Excel dataField@showDataAs)
                    showDataAs: z
                      .enum(['percentOfTotal', 'percentOfRow', 'percentOfCol'])
                      .optional(),
                    /// calculated field: formula over source field names (basic
                    /// arithmetic) + the new field name; agg is fixed to sum
                    formula: z.string().min(1).max(500).optional(),
                    calcName: z.string().min(1).max(128).optional(),
                  })
                  .refine((value) => value.formula !== undefined || value.field !== undefined, {
                    message: '值字段需要 field 或 formula。',
                  })
                  .refine((value) => value.formula === undefined || value.calcName !== undefined, {
                    message: '计算字段需要 calcName。',
                  }),
              )
              .min(1)
              .max(8),
            /// label/value filters on row/column dimension fields; filtered-out
            /// members become hidden items (h="1") and leave the baked layout
            filters: z
              .array(
                z.union([
                  z
                    .object({
                      field: z.string().min(1).max(128),
                      kind: z.literal('label'),
                      op: z.enum(['equal', 'contains', 'beginsWith']),
                      value: z.string().min(1).max(128),
                    })
                    .strict(),
                  z
                    .object({
                      field: z.string().min(1).max(128),
                      kind: z.literal('value'),
                      op: z.literal('top'),
                      /// name of the value entry being measured (field or calcName)
                      measure: z.string().min(1).max(128),
                      count: z.number().int().min(1).max(100),
                    })
                    .strict(),
                  z
                    .object({
                      field: z.string().min(1).max(128),
                      kind: z.literal('value'),
                      op: z.literal('greaterThan'),
                      measure: z.string().min(1).max(128),
                      from: z.number().finite(),
                    })
                    .strict(),
                  z
                    .object({
                      field: z.string().min(1).max(128),
                      kind: z.literal('value'),
                      op: z.literal('between'),
                      measure: z.string().min(1).max(128),
                      from: z.number().finite(),
                      to: z.number().finite(),
                    })
                    .strict(),
                ]),
              )
              .max(5)
              .optional(),
            /// grouping rules for row/column dimension fields (date units
            /// merge across years; numeric range buckets are half-open)
            groupings: z
              .array(
                z.union([
                  z
                    .object({
                      field: z.string().min(1).max(128),
                      kind: z.literal('date'),
                      dateUnit: z.enum(['year', 'quarter', 'month']),
                    })
                    .strict(),
                  z
                    .object({
                      field: z.string().min(1).max(128),
                      kind: z.literal('range'),
                      rangeStep: z.number().positive().finite(),
                      rangeStart: z.number().finite().optional(),
                    })
                    .strict(),
                ]),
              )
              .max(4)
              .optional(),
          })
          .strict(),
      )
      .max(5)
      .optional(),
    /// refreshes every pivot cache against its current source (new members
    /// append to sharedItems; Excel rebuilds the layout via refreshOnLoad)
    refreshPivots: z.boolean().optional(),
    /// grows pivot output areas after a refresh yields new members; the grown
    /// cells must be empty (fail-closed on existing content)
    expandPivots: z
      .array(
        z
          .object({
            pivot: z.string().min(1).max(64),
            /// new full output ref including header and grand totals
            outputRef: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$/),
          })
          .strict(),
      )
      .max(5)
      .optional(),
    /// sheet protection toggle (no password — unprotecting a password-
    /// protected sheet fails closed)
    protectSheets: z
      .array(z.object({ sheet: z.string().min(1).max(64), protect: z.boolean() }).strict())
      .max(10)
      .optional(),
    /// workbook structure lock
    protectWorkbook: z.object({ lockStructure: z.boolean() }).strict().optional(),
    /// page layout per sheet (print + view options; print areas/titles are
    /// sheet-scoped defined names; null clears)
    /// creates Excel tables (ListObjects) over value ranges; column names
    /// come from the header row (non-blank, unique)
    addTables: z
      .array(
        z
          .object({
            sheet: z.string().min(1).max(64),
            /// range including the header row, e.g. "A1:C10"
            range: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$/),
            name: z.string().min(1).max(64),
            /// built-in style name; omitted = TableStyleMedium2
            style: z.string().min(1).max(64).optional(),
            bandedRows: z.boolean(),
          })
          .strict(),
      )
      .max(5)
      .optional(),
    /// applies a workbook theme: 12 palette colors (#RRGGBB, renderer index
    /// order) and/or major/minor fonts
    setTheme: z
      .object({
        name: z.string().min(1).max(64),
        colors: z.array(z.string().regex(/^#[0-9A-Fa-f]{6}$/)).length(12).optional(),
        fonts: z
          .object({ major: z.string().min(1).max(64), minor: z.string().min(1).max(64) })
          .strict()
          .optional(),
      })
      .strict()
      .refine((theme) => theme.colors !== undefined || theme.fonts !== undefined, {
        message: 'A theme operation requires colors or fonts.',
      })
      .optional(),
    setPageSetups: z
      .array(
        z
          .object({
            sheet: z.string().min(1).max(64),
            orientation: z.enum(['portrait', 'landscape']).optional(),
            paperSize: z.number().int().min(1).max(200).optional(),
            scale: z.number().int().min(10).max(400).optional(),
            fitToPage: z.boolean().optional(),
            fitToWidth: z.number().int().min(1).max(100).optional(),
            fitToHeight: z.number().int().min(1).max(100).optional(),
            margins: z.enum(['normal', 'wide', 'narrow']).optional(),
            printGridlines: z.boolean().optional(),
            printHeadings: z.boolean().optional(),
            printArea: z
              .string()
              .regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$/)
              .nullable()
              .optional(),
            printTitles: z.string().regex(/^[1-9][0-9]{0,6}:[1-9][0-9]{0,6}$/).nullable().optional(),
          })
          .strict(),
      )
      .max(5)
      .optional(),
  })
  .strict()

export type RuleOps = z.infer<typeof ruleOpsSchema>

export const aiWriteOpsSchema = z
  .object({
    /// target sheet name; omitted = the first sheet
    sheet: z.string().min(1).max(64).optional(),
    /// sorts value rows in a range (formulas inside are rejected — moving
    /// formula text would silently re-target relative references)
    sortRange: z
      .array(
        z
          .object({
            range: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$/),
            /// key column letter, e.g. "B"
            byColumn: z.string().regex(/^[A-Z]{1,3}$/),
            ascending: z.boolean(),
            hasHeader: z.boolean(),
          })
          .strict(),
      )
      .max(5)
      .optional(),
    /// flash fill: infers a concatenation template from the leading example
    /// rows of sourceRange and fills the target column for the remaining rows
    flashFill: z
      .array(
        z
          .object({
            /// source columns + data rows, e.g. "A2:C10"
            sourceRange: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$/),
            /// column letter whose cells the fill writes; must lie in sourceRange
            targetColumn: z.string().regex(/^[A-Z]{1,3}$/),
            /// leading rows that demonstrate the desired output
            exampleCount: z.number().int().min(1).max(20),
          })
          .strict(),
      )
      .max(5)
      .optional(),
    setCells: z
      .array(
        z
          .object({
            cell: z.string().regex(CELL_REF),
            value: z.union([z.string().max(32000), z.number().finite(), z.boolean(), z.null()]),
          })
          .strict(),
      )
      .max(500)
      .optional(),
    setFormulas: z
      .array(
        z
          .object({
            cell: z.string().regex(CELL_REF),
            /// stored with or without the leading '='; the applier normalizes
            formula: z.string().min(2).max(1000),
          })
          .strict(),
      )
      .max(200)
      .optional(),
    setStyles: z
      .array(
        z
          .object({
            /// min(2): a single-cell range like "A1" is two characters; the
            /// previous min(3) silently rejected every short single-cell ref
            range: z.string().min(2).max(64),
            style: workbookStyleEditSchema,
          })
          .strict(),
      )
      .max(100)
      .optional(),
    /// data tools: 分列 lands tokens right of a single-column range (value
    /// level, live grid); 删除重复行 removes whole rows (package level, reload)
    textToColumns: z
      .object({
        sheet: z.string().min(1).max(64),
        range: z.string().min(2).max(64),
        delimiter: z.string().min(1).max(16),
        treatConsecutiveAsOne: z.boolean().optional(),
      })
      .strict()
      .optional(),
    deleteDuplicates: z
      .object({
        sheet: z.string().min(1).max(64),
        range: z.string().min(2).max(64),
        columns: z.array(z.number().int().min(0).max(16383)).max(64).optional(),
        hasHeader: z.boolean().optional(),
      })
      .strict()
      .optional(),
    /// workbook-level defined names (名称管理器): add/replace or remove;
    /// refersTo is a sheet-qualified reference or formula text
    setNames: z
      .object({
        sets: z
          .array(
            z
              .object({
                name: z.string().min(1).max(255),
                refersTo: z.string().min(1).max(500),
              })
              .strict(),
          )
          .max(50)
          .optional(),
        removes: z.array(z.string().min(1).max(255)).max(50).optional(),
      })
      .strict()
      .optional(),
    /// sparklines (迷你图): REPLACES the sheet's set; kind line|column|winLoss
    addSparklines: z
      .array(
        z
          .object({
            kind: z.enum(['line', 'column', 'winLoss']),
            source: z.string().min(2).max(64),
            target: z.string().min(2).max(16),
            color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
            markers: z.boolean().optional(),
            showAxis: z.boolean().optional(),
          })
          .strict(),
      )
      .max(60)
      .optional(),
    /// structural edits (applied to the package; the grid reloads)
    ...structuralOpsSchema.shape,
    /// sheet management (applied to the package; the grid reloads)
    ...sheetOpsSchema.shape,
    /// data validation / conditional formats (applied to the package; reloads)
    ...ruleOpsSchema.shape,
  })
  .strict()

export type AiWriteOps = z.infer<typeof aiWriteOpsSchema>

/// Style edits use the reload path so undo restores the original OOXML style.
/// Structural, sheet and rule changes also require a package reload.
export function hasPackageLevelOps(ops: AiWriteOps): boolean {
  return (
    (ops.setStyles?.length ?? 0) +
      (ops.insertRows?.length ?? 0) +
      (ops.deleteRows?.length ?? 0) +
      (ops.insertColumns?.length ?? 0) +
      (ops.deleteColumns?.length ?? 0) +
      (ops.renameSheet?.length ?? 0) +
      (ops.addSheet?.length ?? 0) +
      (ops.deleteSheet?.length ?? 0) +
      (ops.setDataValidations?.length ?? 0) +
      (ops.setConditionalFormats?.length ?? 0) +
      (ops.editCharts?.length ?? 0) +
      (ops.addCharts?.length ?? 0) +
      (ops.setNotes?.length ?? 0) +
      (ops.addPivot?.length ?? 0) +
      (ops.refreshPivots ? 1 : 0) +
      (ops.expandPivots?.length ?? 0) +
      (ops.protectSheets?.length ?? 0) +
      (ops.protectWorkbook ? 1 : 0) +
      (ops.setPageSetups?.length ?? 0) +
      (ops.addTables?.length ?? 0) +
      (ops.setTheme ? 1 : 0) +
      (ops.deleteDuplicates ? 1 : 0) +
      (ops.setNames ? 1 : 0) +
      (ops.addSparklines ? 1 : 0) >
    0
  )
}

/// Package-level ops → engine StructuralOp list (Excel 1-based → engine 0-based).
export function toEngineStructuralOps(ops: AiWriteOps): Array<
  | { kind: 'insert-rows'; index: number; count: number }
  | { kind: 'remove-rows'; index: number; count: number }
  | { kind: 'insert-cols'; index: number; count: number }
  | { kind: 'remove-cols'; index: number; count: number }
> {
  return [
    ...(ops.insertRows ?? []).map((entry) => ({ kind: 'insert-rows' as const, index: entry.at - 1, count: entry.count })),
    ...(ops.deleteRows ?? []).map((entry) => ({ kind: 'remove-rows' as const, index: entry.at - 1, count: entry.count })),
    ...(ops.insertColumns ?? []).map((entry) => ({ kind: 'insert-cols' as const, index: entry.at - 1, count: entry.count })),
    ...(ops.deleteColumns ?? []).map((entry) => ({ kind: 'remove-cols' as const, index: entry.at - 1, count: entry.count })),
  ]
}

function normalizeFormula(formula: string): string {
  return formula.startsWith('=') ? formula : `=${formula}`
}

/// import snapshot's logical style for a cell (undefined = default).
export function importedStyleOf(
  model: WorkbookModel,
  sheetName: string,
  address: string,
): LogicalStyle | undefined {
  const sheet = model.sheets.find((candidate) => candidate.name === sheetName)
  const cell = sheet?.cells[address] as ModelCell | undefined
  if (!cell?.styleIndex) return undefined
  return logicalStyleOf(model.styles, model.styles.cellXfs[cell.styleIndex], model.themePalette)
}

function modelCellOf(model: WorkbookModel, sheetName: string, address: string): ModelCell | undefined {
  return model.sheets.find((candidate) => candidate.name === sheetName)?.cells[address]
}

/// Grid read-back vs import snapshot → engine edits. Value/formula changes
/// and style changes for the same cell merge into one edit.
export function diffToEdits(model: WorkbookModel, readback: ReadbackWorkbook): CellEdit[] {
  const edits: CellEdit[] = []
  const importSheetByName = new Map(model.sheets.map((sheet) => [sheet.name, sheet]))
  for (const sheet of readback.sheets) {
    const importSheet = importSheetByName.get(sheet.name)
    if (!importSheet) continue // a sheet the engine did not import: leave alone
    const addresses = new Set([
      ...Object.keys(importSheet.cells),
      ...Object.keys(sheet.cells),
    ])
    for (const address of addresses) {
      const before = importSheet.cells[address] as ModelCell | undefined
      const after = sheet.cells[address]
      const row = (address.match(/[1-9][0-9]*$/) ?? ['1'])[0]!
      const columnLetters = (address.match(/^[A-Z]{1,3}/) ?? ['A'])[0]!
      const column = lettersToIndex(columnLetters)
      const changedValue =
        after === undefined
          ? before !== undefined && (before.value !== null || before.formula !== undefined)
          : before?.formula !== after.formula || !after.formula && before?.value !== after.value
      const beforeStyle = importedStyleOf(model, sheet.name, address)
      const afterStyle = after?.style
      // The grid drops a cleared cell's style key entirely (Univer clears are
      // s:null → the style entry is deleted, not zeroed). With a styled source
      // cell, a wholly absent read-back style is therefore an explicit clear —
      // "clear formats/all" — and must reach the file as styleReset (xf 0),
      // never as the per-key delta that absence-is-inherited would imply.
      const styleCleared = beforeStyle !== undefined && afterStyle === undefined
      const styleChanged =
        after === undefined ? styleCleared : !logicalStyleEqual(beforeStyle, afterStyle)
      if (!changedValue && !styleChanged) continue

      const cell = after
        ? after.formula !== undefined
          ? { value: null, formula: after.formula }
          : { value: after.value }
        : { value: null }
      const delta = styleDelta(beforeStyle, afterStyle)
      if (!changedValue && delta === undefined && !styleCleared) continue // no-op: inherited style
      edits.push({
        sheetName: sheet.name,
        row: Number(row) - 1,
        column,
        writeValue: changedValue,
        cell,
        ...(delta !== undefined ? { style: delta } : {}),
        ...(delta === undefined && styleCleared ? { styleReset: true } : {}),
      })
    }
  }
  return edits
}

function lettersToIndex(letters: string): number {
  let column = 0
  for (const character of letters) {
    column = column * 26 + character.charCodeAt(0) - 64
  }
  return column - 1
}

function logicalStyleEqual(a: LogicalStyle | undefined, b: LogicalStyle | undefined): boolean {
  if (a === b) return true
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

/// Preview lines for the approval UI: one line per affected cell/range.
function describeConditionalFormat(entry: CfWireRule): string {
  const threshold = (value: Cfvo): string =>
    value.type === 'min' || value.type === 'max' ? value.type : `${value.type}:${String(value.value)}`
  let detail: string
  if (!('kind' in entry)) {
    const highlight = [entry.fillColor, entry.fontColor, entry.bold ? '粗体' : '',
      entry.italic ? '斜体' : '', entry.strike ? '删除线' : '', entry.underline ? '下划线' : '']
      .filter(Boolean).join('/')
    detail = `${entry.operator} ${entry.formula1}${entry.formula2 ? `~${entry.formula2}` : ''}${highlight ? `，高亮 ${highlight}` : ''}`
  } else if (entry.kind === 'colorScale') {
    detail = `色阶 ${entry.stops.map((stop) => `${threshold(stop)} ${stop.color}`).join(' → ')}`
  } else if (entry.kind === 'dataBar') {
    detail = `数据条 ${entry.color}（${threshold(entry.min)} 至 ${threshold(entry.max)}）${entry.showValue === false ? '，隐藏数值' : ''}`
  } else {
    detail = `图标集 ${entry.iconSet}（${entry.thresholds.map((item, index) =>
      index === 0 ? 'percent:0' : `${item.greaterThan ? '>' : '>='}${threshold(item)}`).join(', ')}）${entry.reverse ? '，反转图标' : ''}${entry.showValue === false ? '，隐藏数值' : ''}`
  }
  return `${detail}${entry.stopIfTrue ? '，满足后停止' : ''}`
}

export function describeOps(readback: ReadbackWorkbook, ops: AiWriteOps): string[] {
  const sheetName = ops.sheet ?? readback.sheets[0]?.name ?? ''
  const lines: string[] = []
  for (const entry of ops.setCells ?? []) {
    lines.push(`${sheetName}!${entry.cell} ← ${formatValue(entry.value)}`)
  }
  for (const entry of ops.setFormulas ?? []) {
    lines.push(`${sheetName}!${entry.cell} ← ${normalizeFormula(entry.formula)}`)
  }
  for (const entry of ops.setStyles ?? []) {
    const keys = Object.keys(entry.style).join(', ')
    lines.push(`${sheetName}!${entry.range} 样式: ${keys || '(无变化)'}`)
  }
  for (const entry of ops.sortRange ?? []) {
    lines.push(
      `${sheetName}!${entry.range} 按 ${entry.byColumn} 列${entry.ascending ? '升序' : '降序'}排序${entry.hasHeader ? '（含表头）' : ''}`,
    )
  }
  for (const entry of ops.flashFill ?? []) {
    lines.push(
      `${sheetName}!${entry.sourceRange} 快速填充到 ${entry.targetColumn} 列（前 ${entry.exampleCount} 行为示例）`,
    )
  }
  if (ops.textToColumns) {
    lines.push(
      `${sheetName}!${ops.textToColumns.range} 按分隔符「${ops.textToColumns.delimiter}」分列到右侧`
        + (ops.textToColumns.treatConsecutiveAsOne ? '（连续分隔符视为一个）' : ''),
    )
  }
  if (ops.deleteDuplicates) {
    const compared = ops.deleteDuplicates.columns
      ? `${ops.deleteDuplicates.columns.length} 列参与比较`
      : '全部列参与比较'
    lines.push(
      `${ops.deleteDuplicates.sheet}!${ops.deleteDuplicates.range} 删除重复行（${compared}`
        + (ops.deleteDuplicates.hasHeader ? '，首行为表头' : '') + '，保留首次出现）',
    )
  }
  if (ops.setNames) {
    for (const entry of ops.setNames.sets ?? []) {
      lines.push(`定义名称 ${entry.name} = ${entry.refersTo}`)
    }
    for (const name of ops.setNames.removes ?? []) {
      lines.push(`删除名称 ${name}`)
    }
  }
  if (ops.addSparklines && ops.addSparklines.length > 0) {
    lines.push(
      `${sheetName} 迷你图 ×${ops.addSparklines.length}（整表替换：`
        + ops.addSparklines
            .slice(0, 6)
            .map((spec) => `${spec.kind} ${spec.source}→${spec.target}`)
            .join('、')
        + (ops.addSparklines.length > 6 ? '…' : '')
        + '）',
    )
  }
  for (const entry of ops.insertRows ?? []) lines.push(`${sheetName} 第 ${entry.at} 行前插入 ${entry.count} 行`)
  for (const entry of ops.deleteRows ?? []) lines.push(`${sheetName} 删除第 ${entry.at} 行起 ${entry.count} 行`)
  for (const entry of ops.insertColumns ?? []) lines.push(`${sheetName} 第 ${entry.at} 列前插入 ${entry.count} 列`)
  for (const entry of ops.deleteColumns ?? []) lines.push(`${sheetName} 删除第 ${entry.at} 列起 ${entry.count} 列`)
  for (const entry of ops.renameSheet ?? []) lines.push(`工作表 "${entry.sheet}" 改名为 "${entry.newName}"`)
  for (const entry of ops.addSheet ?? []) lines.push(`新增工作表 "${entry.name}"`)
  for (const entry of ops.deleteSheet ?? []) lines.push(`删除工作表 "${entry.sheet}"`)
  for (const entry of ops.setDataValidations ?? []) {
    const detail = entry.type === 'list' ? `列表 ${entry.formula1 ?? ''}` : `${entry.operator ?? ''} ${entry.formula1 ?? ''}${entry.formula2 ? `~${entry.formula2}` : ''}`
    lines.push(`${entry.sheet}!${entry.sqref} 数据验证（${entry.type} ${detail.trim()}）`)
  }
  for (const entry of ops.setConditionalFormats ?? []) {
    lines.push(`${entry.sheet}!${entry.sqref} 条件格式（${describeConditionalFormat(entry)}）`)
  }
  for (const entry of ops.editCharts ?? []) {
    const changes = [
      entry.title !== undefined ? `标题"${entry.title}"` : '',
      entry.chartType !== undefined ? `类型→${entry.chartType}` : '',
      entry.seriesColors !== undefined
        ? `系列色 ${Object.entries(entry.seriesColors)
            .map(([index, color]) => `#${index}=${color}`)
            .join(',')}`
        : '',
      entry.legend !== undefined ? `图例→${entry.legend}` : '',
      entry.dataLabels !== undefined ? `数据标签→${entry.dataLabels}` : '',
      entry.dataLabelPosition !== undefined ? `标签位置→${entry.dataLabelPosition}` : '',
      entry.dataLabelFormat !== undefined ? `标签格式"${entry.dataLabelFormat}"` : '',
      entry.axisTitles !== undefined
        ? `轴标题 ${entry.axisTitles.category ?? '—'}/${entry.axisTitles.value ?? '—'}`
        : '',
      entry.grouping !== undefined ? `堆叠→${entry.grouping}` : '',
      entry.gridlines !== undefined ? `网格线→${entry.gridlines ? '开' : '关'}` : '',
      entry.valueAxis !== undefined
        ? `值轴 ${entry.valueAxis.min ?? 'auto'}~${entry.valueAxis.max ?? 'auto'}`
        : '',
      entry.gapWidthPct !== undefined ? `间距${entry.gapWidthPct}%` : '',
      entry.holeSizePct !== undefined ? `孔径${entry.holeSizePct}%` : '',
      entry.explosionPct !== undefined || entry.pointExplosions !== undefined ? `饼图分离` : '',
      entry.pointColors !== undefined ? `点色 ${Object.keys(entry.pointColors).length} 系列` : '',
      entry.seriesSet !== undefined ? `整组换系列（${entry.seriesSet.length} 个）` : '',
      entry.series !== undefined ? `改写系列 ${entry.series.map((s) => s.index).join('、')}` : '',
    ]
      .filter(Boolean)
      .join('，')
    lines.push(`图表 ${entry.chart}（${changes}）`)
  }
  for (const entry of ops.addCharts ?? []) {
    const sheetName = entry.sheet ?? ''
    lines.push(
      `${sheetName ? `${sheetName}!` : ''}${entry.dataRange} 新建 ${entry.chartType} 图表${entry.title ? ` "${entry.title}"` : ''}${entry.anchorCell ? `，锚点 ${entry.anchorCell}` : ''}`,
    )
  }
  for (const entry of ops.setNotes ?? []) {
    lines.push(
      entry.notes.length === 0
        ? `清除 ${entry.sheet} 的全部批注`
        : `${entry.sheet} 设置 ${entry.notes.length} 条批注（${entry.notes
            .slice(0, 3)
            .map((note) => note.cell)
            .join('、')}${entry.notes.length > 3 ? ' 等' : ''}）`,
    )
  }
  for (const entry of ops.addPivot ?? []) {
    const groupingText = (entry.groupings ?? [])
      .map((grouping) =>
        grouping.kind === 'date'
          ? `${grouping.field}按${grouping.dateUnit === 'year' ? '年' : grouping.dateUnit === 'quarter' ? '季' : '月'}`
          : `${grouping.field}按区间${grouping.rangeStart ?? 0}+${grouping.rangeStep}`,
      )
      .join('、')
    const filterText = (entry.filters ?? [])
      .map((filter) =>
        filter.kind === 'label'
          ? `${filter.field}标签${filter.op === 'equal' ? '等于' : filter.op === 'contains' ? '包含' : '以…开头'}"${filter.value}"`
          : `${filter.field}值筛选${filter.op === 'top' ? `前${filter.count}` : filter.op === 'greaterThan' ? `>${filter.from}` : `${filter.from}~${filter.to}`}（${filter.measure}）`,
      )
      .join('、')
    lines.push(
      `创建数据透视表 "${entry.name}"（源 ${entry.sourceSheet}!${entry.sourceRange}，行 ${entry.rowFields.join('>')}` +
        `${entry.columnFields?.length ? `，列 ${entry.columnFields.join('>')}` : ''}，值 ${entry.values
          .map((value) => `${value.agg}(${value.formula !== undefined ? `${value.calcName}=${value.formula}` : value.field})${value.showDataAs ? `占比${value.showDataAs === 'percentOfTotal' ? '总计' : value.showDataAs === 'percentOfRow' ? '行' : '列'}` : ''}`)
          .join('、')}${groupingText ? `，分组 ${groupingText}` : ''}${filterText ? `，筛选 ${filterText}` : ''}，输出到 ${entry.targetCell}）`,
    )
  }
  if (ops.refreshPivots) lines.push('刷新全部数据透视表（重读源数据并重建缓存）')
  for (const entry of ops.expandPivots ?? []) {
    lines.push(`扩展数据透视表 "${entry.pivot}" 的输出区域到 ${entry.outputRef}`)
  }
  for (const entry of ops.protectSheets ?? []) {
    lines.push(`${entry.protect ? '保护' : '取消保护'}工作表 "${entry.sheet}"（无密码）`)
  }
  if (ops.protectWorkbook) {
    lines.push(
      ops.protectWorkbook.lockStructure
        ? '锁定工作簿结构（无密码）'
        : '解除工作簿结构保护',
    )
  }
  for (const entry of ops.setPageSetups ?? []) {
    const changes = [
      entry.orientation,
      entry.scale !== undefined ? `缩放 ${entry.scale}%` : '',
      entry.fitToPage !== undefined ? `适应页面 ${entry.fitToPage ? '开' : '关'}` : '',
      entry.margins !== undefined ? `页边距 ${entry.margins}` : '',
      entry.printArea !== undefined
        ? `打印区域 ${entry.printArea ?? '(清除)'}`
        : '',
      entry.printTitles !== undefined
        ? `顶端标题行 ${entry.printTitles ?? '(清除)'}`
        : '',
    ]
      .filter(Boolean)
      .join('，')
    lines.push(`${entry.sheet} 页面设置（${changes || '无变化'}）`)
  }
  for (const entry of ops.addTables ?? []) {
    lines.push(
      `创建表格 "${entry.name}"（${entry.sheet}!${entry.range}${entry.style ? `，样式 ${entry.style}` : ''}${entry.bandedRows ? '，镶边行' : ''}）`,
    )
  }
  if (ops.setTheme) {
    const parts = [
      ops.setTheme.colors ? `12 色调色板` : '',
      ops.setTheme.fonts ? `字体 ${ops.setTheme.fonts.major}/${ops.setTheme.fonts.minor}` : '',
    ].filter(Boolean)
    lines.push(`应用主题 "${ops.setTheme.name}"（${parts.join('，')}）`)
  }
  return lines
}

function formatValue(value: string | number | boolean | null): string {
  if (value === null) return '(清空)'
  if (typeof value === 'string') return value.length > 40 ? `${value.slice(0, 40)}…` : value
  return String(value)
}

export interface ApplyResult {
  /// edits to push into the grid (sheet name + A1 + value/formula/style delta)
  edits: CellEdit[]
  /// reverse ops restoring the previous values (user-facing undo)
  undo: AiWriteOps
}

/// Validates ops against the current read-back (sheet existence, range
/// bounds) and computes the forward edits plus undo ops. Throws on an
/// unknown sheet or an out-of-bounds range.
export function planOps(
  readback: ReadbackWorkbook,
  ops: AiWriteOps,
  maxRow: number,
  maxColumn: number,
): ApplyResult {
  const sheetName = ops.sheet ?? readback.sheets[0]?.name
  const sheet = readback.sheets.find((candidate) => candidate.name === sheetName)
  if (!sheetName || !sheet) throw new Error(`工作表 "${sheetName ?? ''}" 不存在。`)
  const cells = { ...sheet.cells }
  const editsByAddress = new Map<string, CellEdit>()
  const originals = new Map<string, ReadbackCell | undefined>()
  const guardCell = (address: string) => {
    const coordinates = parseAddress(address)
    if (coordinates.row >= Math.min(maxRow, 1_048_576) || coordinates.column >= Math.min(maxColumn, 16_384)) {
      throw new Error(`单元格 ${address} 超出网格范围。`)
    }
    return coordinates
  }
  const guardRange = (range: string) => {
    const bounds = parseRange(range)
    guardCell(formatAddress(bounds.endRow, bounds.endColumn))
    if (rangeCellCount(bounds) > 50_000) throw new Error(`区域 ${range} 超出单次操作范围。`)
    return bounds
  }
  const writeCell = (address: string, cell: CellEdit['cell']) => {
    const coordinates = guardCell(address)
    if (!originals.has(address)) originals.set(address, sheet.cells[address])
    cells[address] = { ...cells[address], ...cell }
    if (!cell.formula) delete cells[address]!.formula
    const previous = editsByAddress.get(address)
    editsByAddress.set(address, {
      ...previous, sheetName, ...coordinates, writeValue: true, cell,
    })
  }
  for (const entry of ops.sortRange ?? []) {
    guardRange(entry.range)
    for (const change of computeSortChanges(entry, (address) => cells[address] ?? { value: null })) {
      writeCell(change.address, { value: change.after })
    }
  }
  for (const entry of ops.flashFill ?? []) {
    const bounds = guardRange(entry.sourceRange)
    const targetColumn = columnIndex(entry.targetColumn)
    if (targetColumn < bounds.startColumn || targetColumn > bounds.endColumn) {
      throw new Error(`填充列 ${entry.targetColumn} 不在源区域 ${entry.sourceRange} 内。`)
    }
    if (bounds.endRow - bounds.startRow + 1 <= entry.exampleCount) {
      throw new Error('快速填充需要示例行之外还有数据行。')
    }
    const sourceColumns: number[] = []
    for (let column = bounds.startColumn; column <= bounds.endColumn; column++) {
      if (column !== targetColumn) sourceColumns.push(column)
    }
    const cellText = (row: number, column: number) => String(cells[formatAddress(row, column)]?.value ?? '')
    const sourceAt = (row: number) => sourceColumns.map((column) => cellText(row, column))
    const examples: FlashFillExample[] = Array.from({ length: entry.exampleCount }, (_, offset) => ({
      source: sourceAt(bounds.startRow + offset),
      output: cellText(bounds.startRow + offset, targetColumn),
    }))
    const template = inferFlashFillTemplate(examples)
    if (!template) throw new Error('快速填充无法从示例中推断拼接模板。')
    for (let row = bounds.startRow + entry.exampleCount; row <= bounds.endRow; row++) {
      writeCell(formatAddress(row, targetColumn), { value: applyFlashFillTemplate(template, sourceAt(row)) })
    }
  }
  for (const entry of ops.setCells ?? []) writeCell(entry.cell, { value: entry.value })
  for (const entry of ops.setFormulas ?? []) {
    writeCell(entry.cell, { value: null, formula: normalizeFormula(entry.formula) })
  }
  // text-to-columns transforms the values as of THIS payload, so it runs after
  // setCells/setFormulas ("write then split" in one round-trip)
  if (ops.textToColumns) {
    if (ops.textToColumns.sheet !== sheetName) {
      throw new Error(`分列目标工作表 "${ops.textToColumns.sheet}" 与操作工作表 "${sheetName}" 不一致。`)
    }
    const changes = textToColumnChanges(
      ops.textToColumns,
      (row, column) => cells[formatAddress(row, column)]?.value ?? null,
    )
    for (const change of changes) {
      writeCell(formatAddress(change.row, change.column), { value: change.value })
    }
  }
  for (const entry of ops.setStyles ?? []) {
    for (const address of rangeAddresses(guardRange(entry.range))) {
      const coordinates = guardCell(address)
      const previous = editsByAddress.get(address)
      editsByAddress.set(address, {
        sheetName, ...coordinates,
        writeValue: previous?.writeValue ?? false,
        cell: previous?.cell ?? { value: null },
        style: { ...previous?.style, ...entry.style },
      })
    }
  }
  const undoCells: NonNullable<AiWriteOps['setCells']> = []
  const undoFormulas: NonNullable<AiWriteOps['setFormulas']> = []
  for (const [address, before] of originals) {
    if (before?.formula) undoFormulas.push({ cell: address, formula: before.formula })
    else undoCells.push({ cell: address, value: before?.value ?? null })
  }
  return {
    edits: [...editsByAddress.values()],
    undo: {
      sheet: sheetName,
      ...(undoCells.length > 0 ? { setCells: undoCells } : {}),
      ...(undoFormulas.length > 0 ? { setFormulas: undoFormulas } : {}),
    },
  }
}
