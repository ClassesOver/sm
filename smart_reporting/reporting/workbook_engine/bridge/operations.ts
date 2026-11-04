/** Server and browser share the migrated engine's operation protocol. */
import {
  applyCellEdits, applySheetEdits, applyRowColumnOps, applyDvRules, applyCfRules,
  applySheetNotes, addPivotTable, applyColumnWidths, applyRowHeights,
  applyPageSetups, applyTableAdditions, workbookStyleEditSchema,
  refreshPivotCaches, applyPivotLayoutExpansions, expandPivotOutputs,
  applyDefinedNames, protectSheet, protectWorkbookStructure, setThemePart,
  readWorkbook, computeSortChanges, parseAddress, richRunSchema,
} from '@sheets-web/xlsx-engine'
import { z } from 'zod'
import { applySheetMerges } from './merges'

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

export async function applyWorkbookOperations(bytes: Uint8Array, operations: readonly Record<string, any>[]): Promise<Uint8Array> {
  for (const op of operations) {
    switch (op.kind) {
      case 'applyCellEdits': bytes = await applyCellEdits(bytes, z.array(edit).max(1000000).parse(op.edits)); break
      case 'applySheetMerges': bytes = await applySheetMerges(bytes, op.sheetName, op.ranges); break
      case 'applySheetEdits': bytes = await applySheetEdits(bytes, op.plan); break
      case 'applyRowColumnOps': bytes = await applyRowColumnOps(bytes, op.sheetName, op.ops); break
      case 'applyDvRules': bytes = await applyDvRules(bytes, op.rules); break
      case 'applyCfRules': bytes = await applyCfRules(bytes, op.rules); break
      case 'applySheetNotes': bytes = await applySheetNotes(bytes, op.sheetName, op.notes); break
      case 'addPivot': bytes = await addPivotTable(bytes, op.addition); break
      case 'applyColumnWidths': bytes = await applyColumnWidths(bytes, op.sheetName, op.entries); break
      case 'applyRowHeights': bytes = await applyRowHeights(bytes, op.sheetName, op.entries); break
      case 'applyPageSetups': bytes = await applyPageSetups(bytes, op.setups); break
      case 'applyTableAdditions': bytes = await applyTableAdditions(bytes, op.additions); break
      case 'refreshPivotCaches': bytes = await refreshPivotCaches(bytes); break
      case 'applyPivotLayoutExpansions': bytes = await applyPivotLayoutExpansions(bytes, op.updates); break
      case 'expandPivotOutputs': bytes = await expandPivotOutputs(bytes, op.expansions); break
      case 'applyDefinedNames': bytes = await applyDefinedNames(bytes, op.plan); break
      case 'protectSheet': bytes = await protectSheet(bytes, op.sheetName, op.protect); break
      case 'protectWorkbookStructure': bytes = await protectWorkbookStructure(bytes, op.lockStructure); break
      case 'setThemePart': bytes = await setThemePart(bytes, op.themePath, op.state); break
      case 'sortRange': {
        const sheet = (await readWorkbook(bytes)).sheets.find(sheet => sheet.name === op.sheetName)
        if (!sheet) throw new Error('workbook_sheet_missing')
        const changes = computeSortChanges(op.spec, address => sheet.cells[address] ?? { value: null })
        bytes = await applyCellEdits(bytes, changes.map(change => ({
          sheetName: op.sheetName, ...parseAddress(change.address), writeValue: true, cell: { value: change.after },
        })))
        break
      }
      default: throw new Error('workbook_operation_invalid')
    }
  }
  return bytes
}
