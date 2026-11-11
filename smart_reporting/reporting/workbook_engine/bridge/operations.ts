/** Server and browser share the migrated engine's operation protocol. */
import {
  applyCellEdits, applySheetEdits, applyRowColumnOps, applyCellShift, applyDvRules, applyCfRules,
  applySheetNotes, patchSheetNotes, applySheetFilter, addPivotTable, applyColumnWidths,
  applyRowHeights, applyPageSetups, applyTableAdditions, applyTableEdits, workbookStyleEditSchema,
  refreshPivotCaches, applyPivotLayoutExpansions, expandPivotOutputs, sortRangeRows,
  applyDefinedNames, protectSheet, protectWorkbookStructure, setSheetEditableRanges, setThemePart,
  readWorkbook, parseAddress, richRunSchema, applySheetOutline,
} from '@sheets-web/xlsx-engine'
import { applyChartAdditions } from '../packages/xlsx-engine/src/chart-add'
import { applyChartDeletions } from '../packages/xlsx-engine/src/chart-delete'
import { applyChartEdits } from '@sheets-web/xlsx-engine'
import { z } from 'zod'
import { upsertPivotControl, upsertPivotControlRequestSchema, syncOwnedPivotControls, removePivotControl, removePivotControlRequestSchema } from '../packages/xlsx-engine/src/pivot-controls'
import { appendSheetSparklines, appendSheetSparklinesOperationSchema, assertSheetSparklinesShiftable, renameSparklineSheetReferences, removeSheetSparklines, removeSheetSparklinesOperationSchema, editSheetSparklineGroup, editSheetSparklineGroupOperationSchema } from '../packages/xlsx-engine/src/sparkline-additions'
import { applySheetMerges } from './merges'
import { replaceSheetDataValidations } from '../packages/xlsx-engine/src/data-validation-write'
import { replaceConditionalFormattingSnapshots } from '../packages/xlsx-engine/src/conditional-formatting-snapshot'
import { replaceSheetConditionalFormatsOperationSchema } from '../packages/xlsx-engine/src/conditional-formatting-schema'

const cell = z.object({
  value: z.union([z.string(), z.number().finite(), z.boolean(), z.null()]),
  formula: z.string().optional(),
}).strict()
const edit = z.object({
  sheetName: z.string().min(1).max(31), row: z.number().int().min(0).max(1048575),
  column: z.number().int().min(0).max(16383), writeValue: z.boolean(), cell,
  style: workbookStyleEditSchema.optional(), rich: z.array(richRunSchema).optional(),
  styleReset: z.boolean().optional(),
}).strict()
const cellArea = z.object({
  startRow: z.number().int().min(0).max(1048575), endRow: z.number().int().min(0).max(1048575),
  startColumn: z.number().int().min(0).max(16383), endColumn: z.number().int().min(0).max(16383),
}).strict()
const sheetFilterCriteriaSchema = z.object({
  range: cellArea,
  columns: z.array(z.object({
    colId: z.number().int().min(0).max(16383),
    values: z.array(z.string().max(32767)).max(10000).optional(),
    blank: z.boolean().optional(),
    customs: z.object({
      and: z.boolean().optional(),
      filters: z.array(z.object({
        val: z.union([z.string().max(32767), z.number().finite()]),
        operator: z.enum(['equal', 'notEqual', 'greaterThan', 'greaterThanOrEqual', 'lessThan', 'lessThanOrEqual']).optional(),
      }).strict()).min(1).max(2),
    }).strict().optional(),
    dateGroups: z.array(z.object({
      year: z.number().int().min(1).max(9999),
      month: z.number().int().min(1).max(12).optional(),
      day: z.number().int().min(1).max(31).optional(),
      hour: z.number().int().min(0).max(23).optional(),
      minute: z.number().int().min(0).max(59).optional(),
      second: z.number().int().min(0).max(59).optional(),
      dateTimeGrouping: z.enum(['year', 'month', 'day', 'hour', 'minute', 'second']),
    }).strict()).min(1).max(1000).optional(),
  }).strict().refine(column => column.values !== undefined || column.blank !== undefined ||
      column.customs !== undefined || column.dateGroups !== undefined,
    { message: 'A filter column needs values, a blank flag, custom criteria, or date groups.' })).max(1000),
}).strict()

export async function applyWorkbookOperations(bytes: Uint8Array, operations: readonly Record<string, any>[]): Promise<Uint8Array> {
  for (const op of operations) {
    switch (op.kind) {
      case 'applyChartAdditions': bytes = await applyChartAdditions(bytes, op.additions); break
      case 'applyChartDeletions': bytes = await applyChartDeletions(bytes, op.deletions); break
      case 'applyChartEdits': bytes = await applyChartEdits(bytes, op.edits); break
      case 'applyCellEdits': bytes = await applyCellEdits(bytes, z.array(edit).max(1000000).parse(op.edits)); break
      case 'applySheetMerges': bytes = await applySheetMerges(bytes, op.sheetName, op.ranges); break
      case 'applySheetEdits':
        bytes = await renameSparklineSheetReferences(bytes, op.plan.renames)
        bytes = await applySheetEdits(bytes, op.plan); break
      case 'applyRowColumnOps':
        await assertSheetSparklinesShiftable(bytes, op.sheetName)
        bytes = await applyRowColumnOps(bytes, op.sheetName, op.ops); break
      case 'appendSheetSparklines': {
        const parsed = appendSheetSparklinesOperationSchema.parse(op)
        bytes = await appendSheetSparklines(bytes, parsed.sheetName, parsed.groups); break
      }
      case 'removeSheetSparklines': {
        const parsed = removeSheetSparklinesOperationSchema.parse(op)
        bytes = await removeSheetSparklines(bytes, parsed.sheetName, parsed.targets); break
      }
      case 'editSheetSparklineGroup': {
        const parsed = editSheetSparklineGroupOperationSchema.parse(op)
        const { kind: _kind, sheetName, target, ...updates } = parsed
        bytes = await editSheetSparklineGroup(bytes, sheetName, target, updates); break
      }
      case 'applyCellShift': {
        const parsed = z.object({ kind: z.literal('applyCellShift'), sheetName: z.string().min(1).max(31),
          range: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}(?::[A-Z]{1,3}[1-9][0-9]{0,6})?$/),
          shift: z.enum(['right', 'down', 'left', 'up']) }).strict().parse(op)
        await assertSheetSparklinesShiftable(bytes, parsed.sheetName, 'cells')
        bytes = await applyCellShift(bytes, parsed.sheetName, { range: parsed.range, shift: parsed.shift }); break
      }
      case 'applyDvRules': bytes = await applyDvRules(bytes, op.rules); break
      case 'replaceSheetDataValidations': {
        const parsed = z.object({
          kind: z.literal('replaceSheetDataValidations'), sheetName: z.string().min(1).max(31),
          rules: z.array(z.object({ ranges: z.array(cellArea).min(1).max(10000), rule: z.record(z.string(), z.unknown()) }).strict()).max(10000),
        }).strict().parse(op)
        bytes = await replaceSheetDataValidations(bytes, parsed.sheetName, parsed.rules); break
      }
      case 'applyCfRules': bytes = await applyCfRules(bytes, op.rules); break
      case 'replaceSheetConditionalFormats': {
        const parsed = replaceSheetConditionalFormatsOperationSchema.parse(op)
        bytes = await replaceConditionalFormattingSnapshots(bytes, [{ sheetName: parsed.sheetName, rules: parsed.rules }]); break
      }
      case 'patchSheetNotes': {
        const parsed = z.object({ kind: z.literal('patchSheetNotes'), sheetName: z.string().min(1).max(31), sourceIdentity: z.string().regex(/^[a-f0-9]{64}$/),
          changes: z.array(z.union([
            z.object({ row: z.number().int().min(0).max(1048575), column: z.number().int().min(0).max(16383), text: z.string().max(32767).nullable() }).strict(),
            z.object({ fromRow: z.number().int().min(0).max(1048575), fromColumn: z.number().int().min(0).max(16383), toRow: z.number().int().min(0).max(1048575), toColumn: z.number().int().min(0).max(16383) }).strict(),
          ])).max(1000),
        }).strict().parse(op)
        bytes = await patchSheetNotes(bytes, parsed.sheetName, parsed.sourceIdentity, parsed.changes); break
      }
      case 'applySheetNotes': bytes = await applySheetNotes(bytes, op.sheetName, op.notes); break
      case 'applySheetFilter': {
        const parsed = z.object({
          kind: z.literal('applySheetFilter'), sheetName: z.string().min(1).max(31),
          filter: sheetFilterCriteriaSchema.nullable(),
          hiddenRows: z.array(z.number().int().min(0).max(1048575)).max(100000).optional(),
          visibilityRange: cellArea.optional(),
        }).strict().parse(op)
        bytes = await applySheetFilter(bytes, parsed.sheetName, {
          filter: parsed.filter, hiddenRows: parsed.hiddenRows, visibilityRange: parsed.visibilityRange,
        }); break
      }
      case 'addPivot': bytes = await addPivotTable(bytes, op.addition); break
      case 'applyColumnWidths': bytes = await applyColumnWidths(bytes, op.sheetName, op.entries); break
      case 'applySheetOutline': {
        const entry = (max: number) => z.object({ index: z.number().int().min(0).max(max), level: z.number().int().min(0).max(7), collapsed: z.boolean(), hidden: z.boolean().optional() }).strict()
        const parsed = z.object({ kind: z.literal('applySheetOutline'), sheetName: z.string().min(1).max(31), summaryBelow: z.boolean().optional(), summaryRight: z.boolean().optional(), rows: z.array(entry(1048575)).max(1048576).optional(), columns: z.array(entry(16383)).max(16384).optional() }).strict().parse(op)
        const normalize = (entries: NonNullable<typeof parsed.rows>) => entries.map(({ hidden, ...entry }) => ({ ...entry, ...(hidden !== undefined ? { hidden } : {}) }))
        bytes = await applySheetOutline(bytes, parsed.sheetName, {
          ...(parsed.summaryBelow !== undefined ? { summaryBelow: parsed.summaryBelow } : {}),
          ...(parsed.summaryRight !== undefined ? { summaryRight: parsed.summaryRight } : {}),
          ...(parsed.rows !== undefined ? { rows: normalize(parsed.rows) } : {}),
          ...(parsed.columns !== undefined ? { columns: normalize(parsed.columns) } : {}),
        }); break
      }
      case 'applyRowHeights': bytes = await applyRowHeights(bytes, op.sheetName, op.entries); break
      case 'applyPageSetups': bytes = await applyPageSetups(bytes, op.setups); break
      case 'applyTableAdditions': bytes = await applyTableAdditions(bytes, op.additions); break
      case 'applyTableEdits': {
        const parsed = z.object({ kind: z.literal('applyTableEdits'), edits: z.array(z.object({
          worksheetSheetName: z.string().min(1).max(31), tableName: z.string().min(1).max(255),
          name: z.string().min(1).max(255).optional(), area: cellArea.optional(),
          columnNames: z.array(z.string().min(1).max(255)).min(1).max(16384).optional(),
          style: z.string().max(255).optional(), bandedRows: z.boolean().optional(),
          headerRow: z.boolean().optional(), totalsRow: z.boolean().optional(),
          firstColumn: z.boolean().optional(), lastColumn: z.boolean().optional(),
          bandedColumns: z.boolean().optional(), filterButton: z.boolean().optional(), remove: z.literal(true).optional(),
        }).strict()).max(1000) }).strict().parse(op)
        bytes = await applyTableEdits(bytes, parsed.edits); break
      }
      case 'refreshPivotCaches': {
        const before = bytes
        bytes = await refreshPivotCaches(bytes)
        bytes = await syncOwnedPivotControls(before, bytes)
        break
      }
      case 'applyPivotLayoutExpansions': {
        const before = bytes
        bytes = await applyPivotLayoutExpansions(bytes, op.updates)
        const controlRequest = op.controlRequest === undefined ? undefined : upsertPivotControlRequestSchema.parse(op.controlRequest)
        bytes = await syncOwnedPivotControls(before, bytes, undefined, controlRequest)
        break
      }
      case 'removePivotControl': {
        const parsed = z.object({ kind: z.literal('removePivotControl'), request: removePivotControlRequestSchema }).strict().parse(op)
        bytes = await removePivotControl(bytes, parsed.request)
        break
      }
      case 'upsertPivotControl': {
        const parsed = z.object({ kind: z.literal('upsertPivotControl'), request: upsertPivotControlRequestSchema }).strict().parse(op)
        bytes = await upsertPivotControl(bytes, parsed.request)
        break
      }
      case 'expandPivotOutputs': bytes = await expandPivotOutputs(bytes, op.expansions); break
      case 'applyDefinedNames': bytes = await applyDefinedNames(bytes, op.plan); break
      case 'protectSheet': bytes = await protectSheet(bytes, op.sheetName, op.protect); break
      case 'setSheetEditableRanges': {
        const parsed = z.object({ kind: z.literal('setSheetEditableRanges'), sheetName: z.string().min(1).max(31),
          ranges: z.array(z.object({ name: z.string().trim().min(1).max(255), sqref: z.string().min(1).max(32767) }).strict()).max(1000),
        }).strict().parse(op)
        bytes = await setSheetEditableRanges(bytes, parsed.sheetName, parsed.ranges); break
      }
      case 'protectWorkbookStructure': bytes = await protectWorkbookStructure(bytes, op.lockStructure); break
      case 'setThemePart': bytes = await setThemePart(bytes, op.themePath, op.state); break
      case 'sortRange': {
        bytes = await sortRangeRows(bytes, op.sheetName, op.spec)
        break
      }
      default: throw new Error('workbook_operation_invalid')
    }
  }
  return bytes
}
