/// Pivot table creation, ported (lean) from genoffice xlsx-pivot-add.ts:
/// multi-level row/column axes, up to N value fields (sum/count/average/
/// max/min), pre-populated cache records (so LibreOffice/WPS show values
/// without a refresh), full package wiring. Multi-level axes use tabular
/// layout with OOXML r-repeat axis items, mirroring genoffice's
/// buildAxisItemsXml carry rules. Grouping, calculated fields, and filters
/// stay desktop-only and are refused by the input shape.

import { columnLabel, parseRange, parseAddress } from './cell-address'
import { z } from 'zod'
import { decodeXmlText, readXmlAttribute } from './xml'
import { groupLabel, isValidGrouping, type PivotFieldGrouping } from './pivot-grouping'
import type { PivotFilterDef } from './pivot-filters'
import { formatPivotFormula, parsePivotFormula } from './pivot-formula'
import {
  buildPivotLayout,
  pivotOutputArea,
  areasOverlap,
  type PivotLayout,
  type PivotLayoutSpec,
} from './pivot-layout'
import {
  escapeXmlAttribute as escapeAttribute,
  readSourceAreaGrid,
  readSharedStrings,
  readSourceAreaRows,
  assertSafePivotPackage,
  type SourceValue,
} from './pivot-source'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { applyCellEdits, type CellEdit } from './workbook-write'
import { assemblePackage, createBufferEntrySource, type EntrySource } from './zip'

const CONTENT_TYPES_PATH = '[Content_Types].xml'

export class PivotAddError extends Error {}

export interface PivotArea {
  readonly startRow: number
  readonly startColumn: number
  readonly endRow: number
  readonly endColumn: number
}

export interface PivotValueSpec {
  /// Source field index; -1 for calculated fields (formula present).
  readonly fieldIndex: number
  readonly agg: 'sum' | 'count' | 'average' | 'max' | 'min'
  /// Optional Excel number format string for this data field (e.g. "#,##0.00")
  readonly numFmt?: string | undefined
  /// "Show values as" mode (ECMA-376 dataField@showDataAs): percent of grand
  /// total / row / column; undefined = normal.
  readonly showDataAs?: 'percentOfTotal' | 'percentOfRow' | 'percentOfCol' | undefined
  /// Calculated field: formula (references source field names, basic arithmetic)
  /// and the new field name. Written as a <cacheField formula=… databaseField="0">
  /// appended at the end of cacheFields, taking no cache records; agg is fixed to
  /// sum.
  readonly formula?: string | undefined
  readonly calcName?: string | undefined
}

/// Grouping rule for one dimension field (fieldIndex points into fieldNames).
export type PivotAddGrouping = { readonly fieldIndex: number } & PivotFieldGrouping

/// One line of a multi-level axis layout: a data row (t='data', members cover
/// all levels) or a subtotal row (t='default', members hold the fixed prefix).
export interface PivotAxisLine {
  readonly t: 'data' | 'default'
  readonly members: readonly number[]
}

export interface PivotAddition {
  /// Sheet that receives the pivot output.
  readonly worksheetSheetName: string
  /// Name of the source sheet.
  readonly sourceSheetName: string
  readonly sourceArea: PivotArea
  /// Baked output area, headers and grand totals included.
  readonly location: PivotArea
  readonly name: string
  /// All source headers in column order — the cacheFields order.
  readonly fieldNames: readonly string[]
  /// Row dimension field indices, outer level first (1+ levels).
  readonly rowFieldIndices: readonly number[]
  /// Column dimension field indices, outer level first (0+ levels).
  readonly columnFieldIndices?: readonly number[] | undefined
  /// Deduplicated members per row level (level order).
  readonly rowLevelItems: readonly (readonly string[])[]
  /// Row-by-row layout of the data rows (excluding header + grand total).
  readonly rowLines: readonly PivotAxisLine[]
  /// Deduplicated members per column level.
  readonly colLevelItems?: readonly (readonly string[])[]
  /// Column-by-column layout of the data columns.
  readonly colLines?: readonly PivotAxisLine[]
  readonly values: readonly PivotValueSpec[]
  /// Grouping rules for dimension fields (date/numeric ranges): the field's
  /// member table holds group labels and raw source values are grouped by the
  /// same rule before records are written.
  readonly groupings?: readonly PivotAddGrouping[] | undefined
  /// Value/label filters: applied to row/column dimension fields; filtered-out
  /// members are marked hidden via rowHiddenItems/colHiddenItems, and layout
  /// lines exclude them.
  readonly filters?: readonly PivotFilterDef[] | undefined
  /// Filter-hidden member indices per row level (rowLevelItems order).
  readonly rowHiddenItems?: readonly (readonly number[])[] | undefined
  /// Filter-hidden member indices per column level (colLevelItems order).
  readonly colHiddenItems?: readonly (readonly number[])[] | undefined
  /// Output matrix dimensions, inferred by buildPivotLayout when absent.
}

const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const PIVOT_CACHE_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheDefinition'
const PIVOT_RECORDS_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheRecords'
const PIVOT_TABLE_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotTable'
const PIVOT_CACHE_CONTENT_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml'
const PIVOT_RECORDS_CONTENT_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheRecords+xml'
const PIVOT_TABLE_CONTENT_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.pivotTable+xml'

const AGG_CAPTIONS: Record<PivotValueSpec['agg'], string> = {
  sum: 'Sum',
  count: 'Count',
  average: 'Average',
  max: 'Max',
  min: 'Min',
}

/// OOXML dataField@subtotal values; sum is the default and stays implicit.
const AGG_SUBTOTALS: Record<PivotValueSpec['agg'], string | null> = {
  sum: null,
  count: 'count',
  average: 'avg',
  max: 'max',
  min: 'min',
}

const NUM_FMT_IDS: Record<string, number> = {
  '0': 1,
  '0.00': 2,
  '#,##0': 3,
  '#,##0.00': 4,
  '0%': 9,
  '0.00%': 10,
  '0.00E+00': 11,
  '# ?/?': 12,
  '# ??/??': 13,
  'mm-dd-yy': 14,
  'm/d/yyyy': 14,
  'd-mmm-yy': 15,
  'h:mm AM/PM': 18,
  'h:mm:ss AM/PM': 19,
  'h:mm': 20,
  'h:mm:ss': 21,
  '#,##0.00;(#,##0.00)': 4,
  '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)': 164,
}

/// Value specs in calculated-field form (formula present; fieldIndex is -1).
function calcValueSpecsOf(addition: PivotAddition): readonly PivotValueSpec[] {
  return addition.values.filter((value) => value.formula !== undefined)
}

interface ComputedPivot {
  readonly addition: PivotAddition
  readonly matrix: readonly (readonly (string | number | null)[])[ ]
  readonly numberFormats: readonly { readonly columnOffset: number; readonly format: string }[]
  readonly sourceRows: readonly SourceValue[][]
}

function additionSpec(addition: PivotAddition): PivotLayoutSpec {
  const field = (index: number): string => addition.fieldNames[index] ?? ''
  return {
    rowFields: addition.rowFieldIndices.map(field),
    ...(addition.columnFieldIndices && addition.columnFieldIndices.length > 0
      ? { columnField: addition.columnFieldIndices.map(field) }
      : {}),
    values: addition.values.map((value) => ({
      field:
        value.formula === undefined ? field(value.fieldIndex) : (value.calcName ?? ''),
      agg: value.agg,
      ...(value.numFmt !== undefined ? { numFmt: value.numFmt } : {}),
      ...(value.showDataAs !== undefined ? { showDataAs: value.showDataAs } : {}),
      ...(value.formula !== undefined ? { formula: value.formula } : {}),
    })),
    ...(addition.groupings && addition.groupings.length > 0
      ? {
          groupings: addition.groupings.map(({ fieldIndex, ...grouping }) => ({
            field: field(fieldIndex),
            ...grouping,
          })),
        }
      : {}),
    ...(addition.filters && addition.filters.length > 0
      ? {
          filters: addition.filters.map((filter) =>
            filter.kind === 'label'
              ? { ...filter, field: field(filter.field) }
              : { ...filter, field: field(filter.field), valueIndex: filter.dataField },
          ),
        }
      : {}),
  }
}

function hiddenLabels(
  indices: readonly (readonly number[])[] | undefined,
  items: readonly (readonly string[])[],
): string[][] | undefined {
  if (!indices || indices.length === 0) return undefined
  return indices.map((level, index) =>
    level.flatMap((member) => (items[index]?.[member] === undefined ? [] : [items[index]![member]!])),
  )
}

function normalizedAddition(
  original: PivotAddition,
  layout: PivotLayout,
): PivotAddition {
  const definition = layout.definition
  const columnIndices = original.columnFieldIndices ?? []
  const colItems =
    columnIndices.length === 0
      ? undefined
      : columnIndices.length === 1
        ? [definition.columnItems ?? []]
        : definition.colLevelItems ?? []
  const base: PivotAddition = {
    ...original,
    location: pivotOutputArea(
      { row: original.location.startRow, column: original.location.startColumn },
      layout,
    ),
    rowFieldIndices: definition.rowFieldIndices,
    rowLevelItems: definition.rowLevelItems,
    rowLines: definition.rowLines,
    rowHiddenItems: definition.rowHiddenItems,
    values: definition.values,
  }
  if (columnIndices.length > 0) {
    return {
      ...base,
      columnFieldIndices: columnIndices,
      colLevelItems: colItems ?? [],
      colLines: definition.colLines ?? [],
      ...(definition.groupings ? { groupings: definition.groupings } : {}),
      ...(definition.filters ? { filters: definition.filters } : {}),
      ...(definition.colHiddenItems ? { colHiddenItems: definition.colHiddenItems } : {}),
    }
  }
  const withoutColumns = (({ columnFieldIndices: _columnFieldIndices, colLevelItems: _colLevelItems, colLines: _colLines, ...rest }) => rest)(base)
  return {
    ...withoutColumns,
    ...(definition.groupings ? { groupings: definition.groupings } : {}),
    ...(definition.filters ? { filters: definition.filters } : {}),
    ...(definition.colHiddenItems ? { colHiddenItems: definition.colHiddenItems } : {}),
  }
}

function cellEditsForLayout(
  addition: PivotAddition,
  matrix: readonly (readonly (string | number | null)[])[],
  numberFormats: readonly { readonly columnOffset: number; readonly format: string }[],
): CellEdit[] {
  const formats = new Map(numberFormats.map((entry) => [entry.columnOffset, entry.format]))
  const edits: CellEdit[] = []
  matrix.forEach((row, rowOffset) => {
    row.forEach((value, columnOffset) => {
      const format = formats.get(columnOffset)
      edits.push({
        sheetName: addition.worksheetSheetName,
        row: addition.location.startRow + rowOffset,
        column: addition.location.startColumn + columnOffset,
        writeValue: true,
        cell: { value },
        ...(format ? { style: { numberFormat: format } } : {}),
      })
    })
  })
  return edits
}

async function computePivot(
  source: EntrySource,
  workbookXml: string,
  addition: PivotAddition,
): Promise<ComputedPivot> {
  const element = parseSheetElements(workbookXml).find(
    (entry) => entry.name === addition.sourceSheetName,
  )
  if (!element?.relationshipId) throw new PivotAddError(`Sheet "${addition.sourceSheetName}" was not found.`)
  const worksheetPath = await resolveWorksheetPath(source, element.relationshipId)
  const worksheetXml = await source.readText(worksheetPath)
  const grid = await readSourceAreaGrid(
    source,
    worksheetXml,
    addition.sourceArea.startRow,
    addition.sourceArea.endRow,
    addition.sourceArea.startColumn,
    addition.sourceArea.endColumn,
  )
  const layout = buildPivotLayout(grid, additionSpec(addition), undefined, {
    memberOrder: {
      rowLevelItems: addition.rowLevelItems,
      ...(addition.colLevelItems ? { colLevelItems: addition.colLevelItems } : {}),
    },
    hiddenMembers: {
      row: hiddenLabels(addition.rowHiddenItems, addition.rowLevelItems),
      column: hiddenLabels(addition.colHiddenItems, addition.colLevelItems ?? []),
    },
  })
  const normalized = normalizedAddition(addition, layout)
  validateAddition(normalized, true)
  return {
    addition: normalized,
    matrix: layout.matrix,
    numberFormats: layout.numberFormats,
    sourceRows: grid.slice(1),
  }
}

function areaToRef(area: PivotArea): string {
  return `${columnLabel(area.startColumn)}${area.startRow + 1}:${columnLabel(area.endColumn)}${area.endRow + 1}`
}

const pivotAreaSchema = z.object({
  startRow: z.number().int().min(0).max(1048575),
  endRow: z.number().int().min(0).max(1048575),
  startColumn: z.number().int().min(0).max(16383),
  endColumn: z.number().int().min(0).max(16383),
}).refine((area) => area.endRow >= area.startRow && area.endColumn >= area.startColumn)
const memberTablesSchema = z.array(z.array(z.string()).max(10000)).max(200)
const pivotStateSchema = z.object({
  worksheetSheetName: z.string().min(1), sourceSheetName: z.string().min(1),
  sourceArea: pivotAreaSchema, location: pivotAreaSchema, name: z.string().min(1),
  fieldNames: z.array(z.string().min(1)).min(1).max(200),
  rowFieldIndices: z.array(z.number().int().nonnegative()).min(1).max(200),
  columnFieldIndices: z.array(z.number().int().nonnegative()).max(200).optional(),
  rowLevelItems: memberTablesSchema, colLevelItems: memberTablesSchema.optional(),
  rowLines: z.array(z.object({ t: z.enum(['data', 'default']), members: z.array(z.number().int().nonnegative()) })).max(20000),
  colLines: z.array(z.object({ t: z.enum(['data', 'default']), members: z.array(z.number().int().nonnegative()) })).max(1000).optional(),
  values: z.array(z.object({
    fieldIndex: z.number().int().min(-1), agg: z.enum(['sum', 'count', 'average', 'max', 'min']),
    numFmt: z.string().min(1).max(255).optional(),
    showDataAs: z.enum(['percentOfTotal', 'percentOfRow', 'percentOfCol']).optional(),
    formula: z.string().optional(), calcName: z.string().optional(),
  })).min(1).max(8),
  groupings: z.array(z.union([
    z.object({ fieldIndex: z.number().int().nonnegative(), kind: z.literal('date'), dateUnit: z.enum(['year', 'quarter', 'month']) }),
    z.object({ fieldIndex: z.number().int().nonnegative(), kind: z.literal('range'), rangeStep: z.number().positive(), rangeStart: z.number().optional() }),
  ])).optional(),
  filters: z.array(z.union([
    z.object({ kind: z.literal('label'), field: z.number().int().nonnegative(), op: z.enum(['equal', 'contains', 'beginsWith']), value: z.string() }),
    z.object({ kind: z.literal('value'), field: z.number().int().nonnegative(), dataField: z.number().int().nonnegative(), op: z.enum(['top', 'greaterThan', 'between']), count: z.number().int().positive().optional(), from: z.number().optional(), to: z.number().optional() }),
  ])).optional(),
  rowHiddenItems: z.array(z.array(z.number().int().nonnegative())).optional(),
  colHiddenItems: z.array(z.array(z.number().int().nonnegative())).optional(),
})

export function readPivotState(tableXml: string): PivotAddition | undefined {
  const stateTag = tableXml.match(/<aio:aioPivotState\b[^>]*\/>/)?.[0]
  if (!stateTag) {
    if (tableXml.includes('{AIO-PIVOT-STATE}')) throw new PivotAddError('Invalid persisted pivot state.')
    return undefined
  }
  try {
    const state = pivotStateSchema.parse(JSON.parse(decodeXmlText(readXmlAttribute(stateTag, 'v') ?? ''))) as PivotAddition
    validateAddition(state, true)
    return state
  } catch (error) {
    throw new PivotAddError(`Invalid persisted pivot state: ${error instanceof Error ? error.message : String(error)}`)
  }
}

function validateAddition(addition: PivotAddition, allowEmpty = false): void {
  const parsed = pivotStateSchema.safeParse(addition)
  if (!parsed.success) throw new PivotAddError('Invalid pivot configuration.')
  const fieldCount = addition.fieldNames.length
  const inBounds = (index: number): boolean => index >= 0 && index < fieldCount
  const rowIndices = addition.rowFieldIndices
  const colIndices = addition.columnFieldIndices ?? []
  if (rowIndices.length === 0 || rowIndices.some((index) => !inBounds(index))) {
    throw new PivotAddError(`Pivot "${addition.name}" references a row field outside its source.`)
  }
  if (colIndices.some((index) => !inBounds(index))) {
    throw new PivotAddError(`Pivot "${addition.name}" references a column field outside its source.`)
  }
  if (new Set([...rowIndices, ...colIndices]).size !== rowIndices.length + colIndices.length) {
    throw new PivotAddError(`Pivot "${addition.name}" cannot use one field on both axes.`)
  }
  if (addition.rowLevelItems.length !== rowIndices.length) {
    throw new PivotAddError(`Pivot "${addition.name}" needs one member table per row level.`)
  }
  if ((addition.columnFieldIndices ?? []).length !== (addition.colLevelItems?.length ?? 0)) {
    throw new PivotAddError(`Pivot "${addition.name}" needs one member table per column level.`)
  }
  if (addition.rowLines.length === 0 && !allowEmpty) {
    throw new PivotAddError(`Pivot "${addition.name}" has no row layout lines.`)
  }
  const validateLines = (
    axis: 'row' | 'column',
    levels: number,
    levelItems: readonly (readonly string[])[],
    lines: readonly PivotAxisLine[],
  ): void => {
    for (const line of lines) {
      if (
        line.members.length === 0 ||
        line.members.length > levels ||
        (axis === 'row' && line.t === 'data' && line.members.length !== levels) ||
        line.members.some((member, level) => member < 0 || member >= (levelItems[level]?.length ?? 0))
      ) {
        throw new PivotAddError(`Pivot "${addition.name}" has an inconsistent ${axis} line.`)
      }
    }
  }
  validateLines('row', rowIndices.length, addition.rowLevelItems, addition.rowLines)
  if (colIndices.length > 0) {
    validateLines('column', colIndices.length, addition.colLevelItems ?? [], addition.colLines ?? [])
  }
  if (addition.values.length === 0 || addition.values.length > 8) {
    throw new PivotAddError(`Pivot "${addition.name}" needs 1-8 value fields.`)
  }
  for (const value of addition.values) {
    // Calculated fields (formula present) carry fieldIndex -1 by convention.
    if (value.formula === undefined && !inBounds(value.fieldIndex)) {
      throw new PivotAddError(`Pivot "${addition.name}" references a value field outside its source.`)
    }
  }
  // Calculated fields: name is required and must not collide with source fields
  // or other calculated fields (case-insensitive); the formula must parse against
  // source field names; aggregation is fixed to sum.
  const calcNames = new Set(addition.fieldNames.map((name) => name.trim().toLowerCase()))
  for (const value of calcValueSpecsOf(addition)) {
    const calcName = (value.calcName ?? '').trim()
    if (calcName === '' || calcNames.has(calcName.toLowerCase()) || value.agg !== 'sum') {
      throw new PivotAddError(`Pivot "${addition.name}" has an invalid calculated field.`)
    }
    calcNames.add(calcName.toLowerCase())
    try {
      parsePivotFormula(value.formula ?? '', addition.fieldNames)
    } catch (error) {
      throw new PivotAddError(
        `Pivot "${addition.name}" has a bad calculated-field formula: ` +
          `${error instanceof Error ? error.message : String(error)}`,
      )
    }
  }
  // With a column field the multi-value <colItems x="-2"> form is not
  // generated, so exactly one value entry is supported (genoffice parity).
  if (colIndices.length > 0 && addition.values.length !== 1) {
    throw new PivotAddError(
      `Pivot "${addition.name}" with a column field supports exactly one values entry.`,
    )
  }
  const sourceWidth = addition.sourceArea.endColumn - addition.sourceArea.startColumn + 1
  if (sourceWidth !== addition.fieldNames.length) {
    throw new PivotAddError(
      `Pivot "${addition.name}" has ${addition.fieldNames.length} field names for a ${sourceWidth}-column source.`,
    )
  }
  // Grouping is only allowed on row/column dimension fields, and the rule itself
  // must be valid (mirrors genoffice validateAddition).
  const dimensionFields = new Set<number>([...rowIndices, ...colIndices])
  for (const { fieldIndex, ...grouping } of addition.groupings ?? []) {
    if (!dimensionFields.has(fieldIndex) || !isValidGrouping(grouping)) {
      throw new PivotAddError(`Pivot "${addition.name}" has an invalid field grouping.`)
    }
  }
  // Filter-hidden member indices must stay within their level's member table.
  const validateHidden = (
    hiddenPerLevel: readonly (readonly number[])[] | undefined,
    levelItems: readonly (readonly string[])[],
  ): boolean =>
    (hiddenPerLevel ?? []).every((hidden, level) =>
      hidden.every((member) => member >= 0 && member < (levelItems[level]?.length ?? 0)),
    )
  if (
    !validateHidden(addition.rowHiddenItems, addition.rowLevelItems) ||
    !validateHidden(addition.colHiddenItems, addition.colLevelItems ?? [])
  ) {
    throw new PivotAddError(`Pivot "${addition.name}" has an out-of-range hidden item.`)
  }
}

/// One raw source row: value per cacheField, in fieldNames order.
async function readSourceRows(
  source: EntrySource,
  workbookXml: string,
  addition: PivotAddition,
): Promise<SourceValue[][]> {
  let worksheetPath: string
  try {
    const element = parseSheetElements(workbookXml).find(
      (entry) => entry.name === addition.sourceSheetName,
    )
    if (element?.relationshipId === undefined) return []
    worksheetPath = await resolveWorksheetPath(source, element.relationshipId)
  } catch {
    return [] // source unreadable: empty records, Excel refreshes on open
  }
  const worksheetXml = await source.readText(worksheetPath)
  return readSourceAreaRows(
    source,
    worksheetXml,
    addition.sourceArea.startRow,
    addition.sourceArea.endRow,
    addition.sourceArea.startColumn,
    addition.sourceArea.endColumn,
  )
}

function buildCacheRecordsXml(
  sourceRows: readonly SourceValue[][],
  addition: PivotAddition,
): string {
  if (sourceRows.length === 0) {
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      `<pivotCacheRecords xmlns="${MAIN_NS}" xmlns:r="${REL_NS}" count="0"/>`
    )
  }
  // Per-level sharedItems lookups for every row/column dimension field.
  const lookups = new Map<number, Map<string, number>>()
  addition.rowFieldIndices.forEach((fieldIndex, level) => {
    lookups.set(
      fieldIndex,
      new Map((addition.rowLevelItems[level] ?? []).map((item, index) => [String(item), index])),
    )
  })
  ;(addition.columnFieldIndices ?? []).forEach((fieldIndex, level) => {
    lookups.set(
      fieldIndex,
      new Map(((addition.colLevelItems ?? [])[level] ?? []).map((item, index) => [String(item), index])),
    )
  })
  // Grouped fields' member tables hold group labels: raw values are grouped by
  // the same rule before records are written.
  const groupingByField = new Map<number, PivotFieldGrouping>()
  for (const { fieldIndex, ...grouping } of addition.groupings ?? []) {
    groupingByField.set(fieldIndex, grouping)
  }
  const records = sourceRows
    .map((row) => {
      const cells = row.map((value, colOffset) => {
        const lookup = lookups.get(colOffset)
        if (lookup !== undefined) {
          const grouping = groupingByField.get(colOffset)
          const key = grouping ? groupLabel(grouping, value) : value === null ? '' : String(value)
          const index = lookup.get(key)
          return index === undefined ? '<m/>' : `<x v="${index}"/>`
        }
        if (value === null || value === '') return '<m/>'
        if (typeof value === 'number') return `<n v="${value}"/>`
        return `<s v="${escapeAttribute(String(value))}"/>`
      })
      return `<r>${cells.join('')}</r>`
    })
    .join('')
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    `<pivotCacheRecords xmlns="${MAIN_NS}" xmlns:r="${REL_NS}" count="${sourceRows.length}">${records}</pivotCacheRecords>`
  )
}

/// Exported for pivot-expand relayout: the cacheDefinition is regenerated
/// from an edited layout, keeping the records rel id.
export function buildCacheDefinitionXml(
  recordsRelId: string,
  addition: PivotAddition,
  recordCount: number,
): string {
  const dimensionFields = new Set<number>([
    ...addition.rowFieldIndices,
    ...(addition.columnFieldIndices ?? []),
  ])
  const levelItemsByField = new Map<number, readonly string[]>()
  addition.rowFieldIndices.forEach((fieldIndex, level) => {
    levelItemsByField.set(fieldIndex, addition.rowLevelItems[level] ?? [])
  })
  ;(addition.columnFieldIndices ?? []).forEach((fieldIndex, level) => {
    levelItemsByField.set(fieldIndex, (addition.colLevelItems ?? [])[level] ?? [])
  })
  const fields = addition.fieldNames
    .map((name, index) => {
      if (!dimensionFields.has(index)) {
        return `<cacheField name="${escapeAttribute(name)}" numFmtId="0"><sharedItems/></cacheField>`
      }
      const items = levelItemsByField.get(index) ?? []
      const sharedItems =
        items.length === 0
          ? '<sharedItems/>'
          : `<sharedItems count="${items.length}">` +
            items.map((item) => `<s v="${escapeAttribute(item)}"/>`).join('') +
            '</sharedItems>'
      return `<cacheField name="${escapeAttribute(name)}" numFmtId="0">${sharedItems}</cacheField>`
    })
    .join('')
  // Calculated fields are appended after all source fields: databaseField="0",
  // no cache records; formulas are normalized to the quoted-reference form.
  const calcSpecs = calcValueSpecsOf(addition)
  const calcFields = calcSpecs
    .map(
      (spec) =>
        `<cacheField name="${escapeAttribute(spec.calcName ?? '')}" ` +
        `formula="${escapeAttribute(formatPivotFormula(parsePivotFormula(spec.formula ?? '', addition.fieldNames)))}" ` +
        'databaseField="0" numFmtId="0"/>',
    )
    .join('')
  const cacheFieldCount = addition.fieldNames.length + calcSpecs.length
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    `<pivotCacheDefinition xmlns="${MAIN_NS}" xmlns:r="${REL_NS}" r:id="${recordsRelId}" ` +
    `refreshedBy="sheets-web" createdVersion="8" refreshedVersion="8" ` +
    `minRefreshableVersion="3" recordCount="${recordCount}">` +
    '<cacheSource type="worksheet">' +
    `<worksheetSource ref="${areaToRef(addition.sourceArea)}" sheet="${escapeAttribute(addition.sourceSheetName)}"/>` +
    '</cacheSource>' +
    `<cacheFields count="${cacheFieldCount}">${fields}${calcFields}</cacheFields>` +
    '</pivotCacheDefinition>'
  )
}

/// Generates <rowItems>/<colItems> per OOXML r (repeat) semantics: members
/// within the common prefix shared with the previous line are omitted, r
/// points at the level of this line's first explicit <x>; subtotal lines are
/// t="default". Ported from genoffice buildAxisItemsXml.
function buildAxisItemsXml(
  lines: readonly PivotAxisLine[],
  levels: number,
  tag: 'rowItems' | 'colItems',
): string {
  const parts: string[] = []
  let carried: (number | null)[] = new Array(levels).fill(null)
  for (const line of lines) {
    const fixed = line.members.length
    let repeat = 0
    // Each line emits at least one <x> as an anchor, so the cap is fixed-1.
    while (
      repeat < fixed - 1 &&
      carried[repeat] !== null &&
      carried[repeat] === line.members[repeat]
    ) {
      repeat += 1
    }
    const xs = line.members
      .slice(repeat)
      .map((member) => (member === 0 ? '<x/>' : `<x v="${member}"/>`))
      .join('')
    parts.push(
      `<i${repeat === 0 ? '' : ` r="${repeat}"`}${line.t === 'data' ? '' : ` t="${line.t}"`}>${xs}</i>`,
    )
    carried = [...line.members]
    while (carried.length < levels) carried.push(null)
  }
  parts.push('<i t="grand"><x/></i>')
  return `<${tag} count="${lines.length + 1}">${parts.join('')}</${tag}>`
}

/// Private extLst extension for grouped-field metadata: Excel ignores unknown
/// ext elements (the file stays valid), and our refresh reads it back so
/// refreshed records still group accordingly. Ported from genoffice
/// buildGroupingExtLst.
/// TODO(OOXML persistence): emit real <fieldGroup> + <rangePr> + <groupItems>
/// so refreshing inside Excel also keeps the grouping (currently a manual
/// Excel refresh degrades to grouping by raw values).
export function buildPivotStateXml(addition: PivotAddition): string {
  // Filter-derived hidden items must be recalculated against refreshed values.
  const filteredFields = new Set((addition.filters ?? []).map((filter) => filter.field))
  const state = {
    ...addition,
    rowHiddenItems: addition.rowHiddenItems?.map((items, level) =>
      filteredFields.has(addition.rowFieldIndices[level]!) ? [] : items),
    colHiddenItems: addition.colHiddenItems?.map((items, level) =>
      filteredFields.has(addition.columnFieldIndices?.[level] ?? -1) ? [] : items),
  }
  return '<ext uri="{AIO-PIVOT-STATE}" xmlns:aio="urn:aioffice:pivot">' +
    `<aio:aioPivotState v="${escapeAttribute(JSON.stringify(state))}"/>` + '</ext>'
}

function buildGroupingExtLst(addition: PivotAddition): string {
  const groupings = addition.groupings ?? []
  return '<extLst>' + buildPivotStateXml(addition) +
    (groupings.length === 0 ? '' :
      '<ext uri="{AIO-PIVOT-GROUPINGS}" xmlns:aio="urn:aioffice:pivot">' +
      `<aio:aioPivotGroupings v="${escapeAttribute(JSON.stringify(groupings))}"/>` + '</ext>') +
    '</extLst>'
}

/// Exported for pivot-expand relayout: the pivotTableDefinition is
/// regenerated from an edited layout, keeping the original name and cacheId.
export function buildPivotTableXml(cacheId: number, addition: PivotAddition): string {
  const rowIndices = addition.rowFieldIndices
  const colIndices = addition.columnFieldIndices ?? []
  const rowLevels = rowIndices.length
  const colLevels = colIndices.length
  // Multi-level rows use tabular layout (compact/outline off) so each level
  // takes one column, matching the baked grid's label columns.
  const tabular = rowLevels >= 2
  const rowItemsOfLevel = (level: number): readonly string[] => addition.rowLevelItems[level] ?? []
  const colItemsOfLevel = (level: number): readonly string[] =>
    (addition.colLevelItems ?? [])[level] ?? []

  const pivotFields = addition.fieldNames
    .map((_name, index) => {
      const rowLevel = rowIndices.indexOf(index)
      if (rowLevel !== -1) {
        return axisPivotField(
          'axisRow',
          rowItemsOfLevel(rowLevel).length,
          tabular,
          new Set(addition.rowHiddenItems?.[rowLevel] ?? []),
        )
      }
      const colLevel = colIndices.indexOf(index)
      if (colLevel !== -1) {
        return axisPivotField(
          'axisCol',
          colItemsOfLevel(colLevel).length,
          tabular,
          new Set(addition.colHiddenItems?.[colLevel] ?? []),
        )
      }
      if (addition.values.some((value) => value.fieldIndex === index)) {
        return `<pivotField dataField="1" showAll="0"${tabular ? ' compact="0" outline="0"' : ''}/>`
      }
      return `<pivotField showAll="0"${tabular ? ' compact="0" outline="0"' : ''}/>`
    })
    .join('')
  // Calculated fields follow the same append order as cacheFields, each taking a
  // value-only pivotField.
  const calcSpecs = calcValueSpecsOf(addition)
  const calcPivotFields = calcSpecs
    .map(
      () => `<pivotField dataField="1" showAll="0"${tabular ? ' compact="0" outline="0"' : ''}/>`,
    )
    .join('')
  const pivotFieldCount = addition.fieldNames.length + calcSpecs.length

  const rowFieldsXml =
    `<rowFields count="${rowLevels}">` +
    rowIndices.map((index) => `<field x="${index}"/>`).join('') +
    '</rowFields>'
  const rowItemsXml = buildAxisItemsXml(addition.rowLines, rowLevels, 'rowItems')

  let columnPart: string
  if (colIndices.length > 0) {
    columnPart =
      `<colFields count="${colIndices.length}">` +
      colIndices.map((index) => `<field x="${index}"/>`).join('') +
      '</colFields>' +
      buildAxisItemsXml(addition.colLines ?? [], colLevels, 'colItems')
  } else if (addition.values.length > 1) {
    columnPart =
      '<colFields count="1"><field x="-2"/></colFields>' +
      `<colItems count="${addition.values.length}">` +
      addition.values
        .map((_value, index) => (index === 0 ? '<i><x/></i>' : `<i i="${index}"><x v="${index}"/></i>`))
        .join('') +
      '</colItems>'
  } else {
    columnPart = '<colItems count="1"><i/></colItems>'
  }

  const dataFields = addition.values
    .map((value) => {
      // A calculated field's fld points at the cacheField appended after the source
      // fields; aggregation is fixed to sum.
      const isCalc = value.formula !== undefined
      const field = isCalc ? (value.calcName ?? '') : (addition.fieldNames[value.fieldIndex] ?? '')
      const fld = isCalc ? addition.fieldNames.length + calcSpecs.indexOf(value) : value.fieldIndex
      const caption = `${AGG_CAPTIONS[value.agg]} of ${field}`
      const subtotal = isCalc ? null : AGG_SUBTOTALS[value.agg]
      // numFmtId: 0 = General; map common patterns to standard Excel IDs.
      // Percent display modes default to 0.00% (id 10) when no format is given.
      const numFmtId = value.numFmt
        ? (NUM_FMT_IDS[value.numFmt.trim()] ?? 0)
        : value.showDataAs !== undefined
          ? 10
          : 0
      return (
        `<dataField name="${escapeAttribute(caption)}" fld="${fld}"` +
        `${subtotal === null ? '' : ` subtotal="${subtotal}"`}` +
        `${value.showDataAs === undefined ? '' : ` showDataAs="${value.showDataAs}"`}` +
        ' baseField="0" baseItem="0"' +
        `${numFmtId !== 0 ? ` numFmtId="${numFmtId}"` : ''}/>`
      )
    })
    .join('')

  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    `<pivotTableDefinition xmlns="${MAIN_NS}" name="${escapeAttribute(addition.name)}" ` +
    `cacheId="${cacheId}" applyNumberFormats="0" applyBorderFormats="0" applyFontFormats="0" ` +
    'applyPatternFormats="0" applyAlignmentFormats="0" applyWidthHeightFormats="1" ' +
    'dataCaption="Values" updatedVersion="8" createdVersion="8" minRefreshableVersion="3" ' +
    'useAutoFormatting="1" itemPrintTitles="1" ' +
    (tabular
      ? 'compact="0" compactData="0" outline="0" outlineData="0" '
      : 'outline="1" outlineData="1" ') +
    'multipleFieldFilters="0">' +
    `<location ref="${areaToRef(addition.location)}" firstHeaderRow="1" ` +
    `firstDataRow="${Math.max(1, colLevels)}" firstDataCol="${rowLevels}"/>` +
    `<pivotFields count="${pivotFieldCount}">${pivotFields}${calcPivotFields}</pivotFields>` +
    rowFieldsXml +
    rowItemsXml +
    columnPart +
    `<dataFields count="${addition.values.length}">${dataFields}</dataFields>` +
    '<pivotTableStyleInfo name="PivotStyleLight16" showRowHeaders="1" showColHeaders="1" ' +
    'showRowStripes="0" showColStripes="0" showLastColumn="1"/>' +
    buildFiltersXml(addition) +
    buildGroupingExtLst(addition) +
    '</pivotTableDefinition>'
  )
}

/// Axis pivotField with per-member items; filtered-out members are written as
/// hidden entries (h="1"), which is how an applied filter is persisted in the
/// file. Ported from genoffice axisPivotField.
function axisPivotField(
  axis: 'axisRow' | 'axisCol',
  itemCount: number,
  tabular = false,
  hidden?: ReadonlySet<number>,
): string {
  const items = Array.from(
    { length: itemCount },
    (_unused, index) => `<item x="${index}"${hidden?.has(index) ? ' h="1"' : ''}/>`,
  ).join('')
  return (
    `<pivotField axis="${axis}" showAll="0"${tabular ? ' compact="0" outline="0"' : ''}>` +
    `<items count="${itemCount + 1}">${items}<item t="default"/></items>` +
    '</pivotField>'
  )
}

/// <filters> block for value/label filters (ECMA-376 CT_PivotFilters): label
/// filters write captionEqual/captionContains/captionBeginsWith + stringValue1;
/// value filters write count (top10)/valueGreaterThan/valueBetween + iMeasureFld;
/// each filter embeds the autoFilter (top10/customFilters) required by the spec.
/// Ported verbatim from genoffice buildFiltersXml.
function buildFiltersXml(addition: PivotAddition): string {
  const filters = addition.filters ?? []
  if (filters.length === 0) return ''
  const entries = filters.map((filter, index) => {
    const id = index + 1
    if (filter.kind === 'label') {
      const type =
        filter.op === 'equal'
          ? 'captionEqual'
          : filter.op === 'contains'
            ? 'captionContains'
            : 'captionBeginsWith'
      // The autoFilter match value expresses contains/begins-with via wildcards
      // (same notation Excel uses).
      const wildcard =
        filter.op === 'equal'
          ? filter.value
          : filter.op === 'contains'
            ? `*${filter.value}*`
            : `${filter.value}*`
      return (
        `<filter fld="${filter.field}" type="${type}" evalOrder="-1" id="${id}" ` +
        `stringValue1="${escapeAttribute(filter.value)}">` +
        '<autoFilter ref="A1"><filterColumn colId="0"><customFilters>' +
        `<customFilter val="${escapeAttribute(wildcard)}"/>` +
        '</customFilters></filterColumn></autoFilter></filter>'
      )
    }
    if (filter.op === 'top') {
      return (
        `<filter fld="${filter.field}" type="count" evalOrder="-1" id="${id}" ` +
        `iMeasureFld="${filter.dataField}">` +
        `<autoFilter ref="A1"><filterColumn colId="0"><top10 val="${filter.count ?? 10}"/>` +
        '</filterColumn></filter>'
      )
    }
    if (filter.op === 'greaterThan') {
      return (
        `<filter fld="${filter.field}" type="valueGreaterThan" evalOrder="-1" id="${id}" ` +
        `iMeasureFld="${filter.dataField}">` +
        '<autoFilter ref="A1"><filterColumn colId="0"><customFilters>' +
        `<customFilter operator="greaterThan" val="${filter.from ?? 0}"/>` +
        '</customFilters></filterColumn></filter>'
      )
    }
    return (
      `<filter fld="${filter.field}" type="valueBetween" evalOrder="-1" id="${id}" ` +
      `iMeasureFld="${filter.dataField}">` +
      '<autoFilter ref="A1"><filterColumn colId="0"><customFilters and="1">' +
      `<customFilter operator="greaterThanOrEqual" val="${filter.from ?? 0}"/>` +
      `<customFilter operator="lessThanOrEqual" val="${filter.to ?? 0}"/>` +
      '</customFilters></filterColumn></filter>'
    )
  })
  return `<filters count="${entries.length}">${entries.join('')}</filters>`
}

function maxCacheId(workbookXml: string): number {
  let max = 0
  for (const match of workbookXml.matchAll(/<pivotCache\b[^>]*\bcacheId="(\d+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return max
}

/// Adds a <pivotCaches> entry; schema order puts pivotCaches after calcPr,
/// before extLst.
function addWorkbookPivotCache(workbookXml: string, cacheId: number, relId: string): string {
  let xml = workbookXml
  if (!/\bxmlns:r\s*=/.test(xml.match(/<workbook\b[^>]*>/)?.[0] ?? '')) {
    xml = xml.replace(/<workbook\b/, () => `<workbook xmlns:r="${REL_NS}"`)
  }
  const entry = `<pivotCache cacheId="${cacheId}" r:id="${relId}"/>`
  if (xml.includes('</pivotCaches>')) {
    return xml.replace('</pivotCaches>', () => `${entry}</pivotCaches>`)
  }
  if (xml.includes('<pivotCaches')) {
    return xml.replace(/<pivotCaches\b[^>]*\/>/, () => `<pivotCaches>${entry}</pivotCaches>`)
  }
  const anchor = xml.includes('</definedNames>') ? '</definedNames>' : '</sheets>'
  if (!xml.includes(anchor)) throw new PivotAddError('workbook.xml has no sheets element.')
  return xml.replace(anchor, () => `${anchor}<pivotCaches>${entry}</pivotCaches>`)
}

function nextRelationshipId(relsXml: string): string {
  let max = 0
  for (const match of relsXml.matchAll(/\bId="rId([0-9]+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return `rId${max + 1}`
}

function appendRelationship(
  relsXml: string,
  type: string,
  target: string,
): { relsXml: string; relId: string } {
  const relId = nextRelationshipId(relsXml)
  return {
    relId,
    relsXml: relsXml.replace(
      '</Relationships>',
      () => `<Relationship Id="${relId}" Type="${type}" Target="${target}"/></Relationships>`,
    ),
  }
}

async function nextFreePath(
  source: EntrySource,
  template: (index: number) => string,
): Promise<string> {
  for (let index = 1; index < 10_000; index += 1) {
    const candidate = template(index)
    if (!(await source.has(candidate))) return candidate
  }
  throw new PivotAddError('No free part name for the pivot parts.')
}

function relsPathFor(partPath: string): string {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash + 1)}_rels/${partPath.slice(slash + 1)}.rels`
}

function relativeTarget(fromPart: string, toPart: string): string {
  const fromDir = fromPart.split('/').slice(0, -1)
  const toSegments = toPart.split('/')
  let common = 0
  while (
    common < fromDir.length &&
    common < toSegments.length - 1 &&
    fromDir[common] === toSegments[common]
  ) {
    common += 1
  }
  const ups = fromDir.length - common
  return `${'../'.repeat(ups)}${toSegments.slice(common).join('/')}`
}

async function registerContentType(
  source: EntrySource,
  replaced: Map<string, string>,
  partPath: string,
  contentType: string,
): Promise<void> {
  const current = replaced.get(CONTENT_TYPES_PATH) ?? (await source.readText(CONTENT_TYPES_PATH))
  if (current.includes(`PartName="/${partPath}"`)) return
  replaced.set(
    CONTENT_TYPES_PATH,
    current.replace(
      '</Types>',
      () => `<Override PartName="/${partPath}" ContentType="${contentType}"/></Types>`,
    ),
  )
}

function EMPTY_RELS_XML(): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '</Relationships>'
  )
}

function containsCell(area: PivotArea, row: number, column: number): boolean {
  return row >= area.startRow && row <= area.endRow && column >= area.startColumn && column <= area.endColumn
}

function worksheetHasContentInArea(worksheetXml: string, area: PivotArea, previous?: PivotArea): boolean {
  for (const cell of worksheetXml.matchAll(/<c\b[^>]*(?:\/>|>[\s\S]*?<\/c>)/g)) {
    const address = readXmlAttribute(cell[0], 'r')
    if (!address) continue
    const { row, column } = parseAddress(address)
    if (!containsCell(area, row, column) || (previous && containsCell(previous, row, column))) continue
    if (/<(?:v|is|f)\b/.test(cell[0])) return true
  }
  return false
}

async function assertOutputAvailable(
  source: EntrySource,
  worksheetPath: string,
  addition: PivotAddition,
  previous?: PivotArea,
  ownTablePath?: string,
): Promise<void> {
  if (addition.worksheetSheetName === addition.sourceSheetName && areasOverlap(addition.location, addition.sourceArea)) {
    throw new PivotAddError('Pivot output conflicts with its source area.')
  }
  const worksheetXml = await source.readText(worksheetPath)
  if (worksheetHasContentInArea(worksheetXml, addition.location, previous)) {
    throw new PivotAddError('Pivot output conflicts with existing worksheet content.')
  }
  for (const merge of worksheetXml.matchAll(/<mergeCell\b[^>]*\/>/g)) {
    const ref = readXmlAttribute(merge[0], 'ref')
    if (ref && areasOverlap(addition.location, parseRange(ref))) {
      throw new PivotAddError('Pivot output conflicts with merged cells.')
    }
  }
  const relsPath = relsPathFor(worksheetPath)
  if (!(await source.has(relsPath))) return
  for (const rel of (await source.readText(relsPath)).matchAll(/<Relationship\b[^>]*\/>/g)) {
    if (readXmlAttribute(rel[0], 'Type') !== PIVOT_TABLE_REL_TYPE) continue
    const target = readXmlAttribute(rel[0], 'Target')
    if (!target) continue
    const tablePath = resolvePivotTarget(worksheetPath, target)
    if (tablePath === ownTablePath) continue
    const tableXml = await source.readText(tablePath)
    const ref = readXmlAttribute(tableXml.match(/<location\b[^>]*\/>/)?.[0] ?? '', 'ref')
    if (ref && areasOverlap(addition.location, parseRange(ref))) {
      throw new PivotAddError('Pivot output conflicts with another pivot table.')
    }
  }
}

export function resolvePivotTarget(partPath: string, target: string): string {
  const parts = target.startsWith('/') ? [] : partPath.split('/').slice(0, -1)
  for (const segment of target.split('/')) {
    if (segment === '..') {
      if (parts.pop() === undefined) throw new PivotAddError('Unsafe pivot relationship target.')
    } else if (segment !== '.' && segment !== '') parts.push(segment)
  }
  return parts.join('/')
}

export async function pivotHostSheet(source: EntrySource, tablePath: string): Promise<{ name: string; path: string }> {
  const workbookXml = await source.readText('xl/workbook.xml')
  for (const sheet of parseSheetElements(workbookXml)) {
    if (!sheet.relationshipId) continue
    const path = await resolveWorksheetPath(source, sheet.relationshipId)
    const relsPath = relsPathFor(path)
    if (!(await source.has(relsPath))) continue
    const rels = await source.readText(relsPath)
    for (const rel of rels.matchAll(/<Relationship\b[^>]*\/>/g)) {
      const target = readXmlAttribute(rel[0], 'Target')
      if (target && readXmlAttribute(rel[0], 'Type') === PIVOT_TABLE_REL_TYPE && resolvePivotTarget(path, target) === tablePath) {
        return { name: sheet.name, path }
      }
    }
  }
  throw new PivotAddError('Pivot table has no resolvable host worksheet.')
}

function appendWorksheetPivotPart(worksheetXml: string, relId: string): string {
  const part = `<pivotTablePart r:id="${relId}"/>`
  const existing = worksheetXml.match(/<pivotTableParts\b([^>]*)>([\s\S]*?)<\/pivotTableParts>/)
  if (existing) {
    const count = Number(existing[1]?.match(/\bcount="(\d+)"/)?.[1] ?? 0) + 1
    const attributes = (existing[1] ?? '').replace(/\s*count="\d+"/, '')
    return worksheetXml.replace(existing[0], () => `<pivotTableParts${attributes} count="${count}">${existing[2] ?? ''}${part}</pivotTableParts>`)
  }
  const selfClosing = worksheetXml.match(/<pivotTableParts\b([^>]*)\/>/)
  if (selfClosing) {
    return worksheetXml.replace(selfClosing[0], () => `<pivotTableParts count="1">${part}</pivotTableParts>`)
  }
  const anchor = worksheetXml.includes('</extLst>') ? '</extLst>' : '</worksheet>'
  return worksheetXml.replace(anchor, () => `<pivotTableParts count="1">${part}</pivotTableParts>${anchor}`)
}

export async function rebuildPivotOutput(
  sourceBytes: Uint8Array,
  tablePath: string,
  cachePath: string,
  requested?: PivotAddition,
  outputArea?: PivotArea,
): Promise<Uint8Array> {
  await assertSafePivotPackage(sourceBytes)
  const source = await createBufferEntrySource(sourceBytes)
  const tableXml = await source.readText(tablePath)
  const state = requested ?? readPivotState(tableXml)
  if (!state) return sourceBytes
  const tableTag = tableXml.match(/<pivotTableDefinition\b[^>]*>/)?.[0] ?? ''
  const name = decodeXmlText(readXmlAttribute(tableTag, 'name') ?? '')
  const cacheId = Number(readXmlAttribute(tableTag, 'cacheId'))
  const oldRef = readXmlAttribute(tableXml.match(/<location\b[^>]*\/>/)?.[0] ?? '', 'ref')
  if (!name || !Number.isInteger(cacheId) || !oldRef) throw new PivotAddError('Invalid pivot table definition.')
  const previous = parseRange(oldRef)
  if ((previous.endRow - previous.startRow + 1) * (previous.endColumn - previous.startColumn + 1) > 250000) {
    throw new PivotAddError('Pivot output is too large to rebuild.')
  }
  const host = await pivotHostSheet(source, tablePath)
  const cacheXml = await source.readText(cachePath)
  const recordsRelId = readXmlAttribute(cacheXml.match(/<pivotCacheDefinition\b[^>]*>/)?.[0] ?? '', 'r:id')
  if (!recordsRelId) throw new PivotAddError('Pivot cache is missing its records relationship.')
  const sourceTag = cacheXml.match(/<worksheetSource\b[^>]*\/>/)?.[0] ?? ''
  const sourceRef = readXmlAttribute(sourceTag, 'ref')
  const sourceSheetName = decodeXmlText(readXmlAttribute(sourceTag, 'sheet') ?? '')
  if (!sourceRef || !sourceSheetName) throw new PivotAddError('Pivot cache is missing its worksheet source.')
  const addition: PivotAddition = {
    ...state,
    name,
    worksheetSheetName: host.name,
    ...(requested ? {} : { sourceArea: parseRange(sourceRef), sourceSheetName }),
    location: requested?.location ?? outputArea ?? previous,
  }
  validateAddition(addition, true)
  const computedResult = await computePivot(source, await source.readText('xl/workbook.xml'), addition)
  // computePivot normalizes the location to the matrix footprint; keep that
  // footprint for stale-cell clearing even when the persisted ref is a larger
  // expanded area, so a shrunken matrix vacates its old cells.
  const matrixArea = computedResult.addition.location
  const computed = (requested !== undefined || outputArea !== undefined)
    ? {
        ...computedResult,
        addition: { ...computedResult.addition, location: addition.location },
      }
    : computedResult
  await assertOutputAvailable(source, host.path, computed.addition, previous, tablePath)
  const rels = await source.readText(relsPathFor(cachePath))
  const recordsRel = [...rels.matchAll(/<Relationship\b[^>]*\/>/g)].find(
    (rel) => readXmlAttribute(rel[0], 'Id') === recordsRelId && readXmlAttribute(rel[0], 'Type') === PIVOT_RECORDS_REL_TYPE,
  )
  const recordsTarget = recordsRel && readXmlAttribute(recordsRel[0], 'Target')
  if (!recordsTarget) throw new PivotAddError('Pivot cache is missing its records part.')
  const replaced = new Map([
    [tablePath, buildPivotTableXml(cacheId, computed.addition)],
    [cachePath, buildCacheDefinitionXml(recordsRelId, computed.addition, computed.sourceRows.length)],
    [resolvePivotTarget(cachePath, recordsTarget), buildCacheRecordsXml(computed.sourceRows, computed.addition)],
  ])
  const edits: CellEdit[] = []
  for (const cell of (await source.readText(host.path)).matchAll(/<c\b[^>]*(?:\/>|>[\s\S]*?<\/c>)/g)) {
    const address = readXmlAttribute(cell[0], 'r')
    if (!address) continue
    const { row, column } = parseAddress(address)
    if (containsCell(previous, row, column) && !containsCell(matrixArea, row, column)) {
      edits.push({ sheetName: host.name, row, column, writeValue: true, cell: { value: null } })
    }
  }
  edits.push(...cellEditsForLayout(computed.addition, computed.matrix, computed.numberFormats))
  const assembled = (await assemblePackage(sourceBytes, {
    replaced, added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [...replaced.keys()],
  })).buffer
  return applyCellEdits(assembled, edits)
}

/// Creates one pivot table: cache definition + records (pre-populated from
/// the source sheet so non-Excel viewers show values without refresh) +
/// pivot table part + worksheet/workbook wiring. Multi-level axes carry
/// per-level member tables and layout lines (tabular layout).
export async function addPivotTable(
  sourceBytes: Uint8Array,
  addition: PivotAddition,
): Promise<Uint8Array> {
  validateAddition(addition)
  await assertSafePivotPackage(sourceBytes)
  const source = await createBufferEntrySource(sourceBytes)
  let workbookXml = await source.readText('xl/workbook.xml')
  let workbookRels = await source.readText('xl/_rels/workbook.xml.rels')

  // name uniqueness across existing pivots
  for (const path of await source.paths()) {
    if (!/^xl\/pivotTables\/[^/]+\.xml$/.test(path)) continue
    const name = (await source.readText(path)).match(
      /<pivotTableDefinition\b[^>]*\bname="([^"]+)"/,
    )?.[1]
    if (name?.toLowerCase() === addition.name.toLowerCase()) {
      throw new PivotAddError(`Pivot name "${addition.name}" is already taken in this workbook.`)
    }
  }

  const targetElement = parseSheetElements(workbookXml).find(
    (entry) => entry.name === addition.worksheetSheetName,
  )
  if (!targetElement?.relationshipId) {
    throw new PivotAddError(`Sheet "${addition.worksheetSheetName}" was not found.`)
  }
  const worksheetPath = await resolveWorksheetPath(source, targetElement.relationshipId)
  const computed = await computePivot(source, workbookXml, addition)
  addition = computed.addition
  const worksheetXml = await source.readText(worksheetPath)
  await assertOutputAvailable(source, worksheetPath, addition)

  const replaced = new Map<string, string>()
  const added = new Map<string, string>()
  const addedEntries: string[] = []
  const touched: string[] = []

  const sourceRows = computed.sourceRows
  const recordsPath = await nextFreePath(
    source,
    (index) => `xl/pivotCache/pivotCacheRecords${index}.xml`,
  )
  added.set(recordsPath, buildCacheRecordsXml(sourceRows, addition))
  addedEntries.push(recordsPath)
  await registerContentType(source, replaced, recordsPath, PIVOT_RECORDS_CONTENT_TYPE)

  const cachePath = await nextFreePath(
    source,
    (index) => `xl/pivotCache/pivotCacheDefinition${index}.xml`,
  )
  let cacheRels = EMPTY_RELS_XML()
  const recordsRel = appendRelationship(
    cacheRels,
    PIVOT_RECORDS_REL_TYPE,
    relativeTarget(cachePath, recordsPath),
  )
  cacheRels = recordsRel.relsXml
  added.set(relsPathFor(cachePath), cacheRels)
  addedEntries.push(relsPathFor(cachePath))
  added.set(cachePath, buildCacheDefinitionXml(recordsRel.relId, addition, sourceRows.length))
  addedEntries.push(cachePath)
  await registerContentType(source, replaced, cachePath, PIVOT_CACHE_CONTENT_TYPE)

  const tablePath = await nextFreePath(source, (index) => `xl/pivotTables/pivotTable${index}.xml`)
  let tableRels = EMPTY_RELS_XML()
  const cacheRel = appendRelationship(
    tableRels,
    PIVOT_CACHE_REL_TYPE,
    relativeTarget(tablePath, cachePath),
  )
  tableRels = cacheRel.relsXml
  added.set(relsPathFor(tablePath), tableRels)
  addedEntries.push(relsPathFor(tablePath))
  const cacheId = maxCacheId(workbookXml) + 1
  added.set(tablePath, buildPivotTableXml(cacheId, addition))
  addedEntries.push(tablePath)
  await registerContentType(source, replaced, tablePath, PIVOT_TABLE_CONTENT_TYPE)

  const worksheetRelsPath = relsPathFor(worksheetPath)
  const worksheetRelsBase = (await source.has(worksheetRelsPath))
    ? await source.readText(worksheetRelsPath)
    : EMPTY_RELS_XML()
  const worksheetRel = appendRelationship(
    worksheetRelsBase,
    PIVOT_TABLE_REL_TYPE,
    relativeTarget(worksheetPath, tablePath),
  )
  if (await source.has(worksheetRelsPath)) {
    replaced.set(worksheetRelsPath, worksheetRel.relsXml)
  } else {
    added.set(worksheetRelsPath, worksheetRel.relsXml)
    addedEntries.push(worksheetRelsPath)
  }

  replaced.set(worksheetPath, appendWorksheetPivotPart(worksheetXml, worksheetRel.relId))
  const workbookRel = appendRelationship(
    workbookRels,
    PIVOT_CACHE_REL_TYPE,
    relativeTarget('xl/workbook.xml', cachePath),
  )
  workbookRels = workbookRel.relsXml
  replaced.set('xl/_rels/workbook.xml.rels', workbookRels)
  workbookXml = addWorkbookPivotCache(workbookXml, cacheId, workbookRel.relId)
  replaced.set('xl/workbook.xml', workbookXml)
  touched.push('xl/workbook.xml', 'xl/_rels/workbook.xml.rels')

  const plan = {
    replaced,
    added,
    addedBinary: new Map<string, Uint8Array>(),
    removedEntries: [] as string[],
    addedEntries,
    touchedEntries: [...new Set([...touched, ...addedEntries])],
  }
  const assembled = (await assemblePackage(sourceBytes, plan)).buffer
  return applyCellEdits(assembled, cellEditsForLayout(addition, computed.matrix, computed.numberFormats))
}
