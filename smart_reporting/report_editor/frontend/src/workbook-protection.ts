/**
 * Review ▸ Protect Sheet / Protect Workbook (fixed source GenOffice f8c17004
 * `ribbon-actions.ts:488-528`, `ExcelShell.tsx:3482-3511`) within what the
 * engine's `protection.ts` writes: password-less sheet protection with Excel's
 * default permissions and the workbook structure lock. Password-protected
 * targets stay as they are (the engine refuses to rewrite their hashes), the
 * dialog's permission flags / password / allow-edit ranges are not offered.
 *
 * A protected sheet is read-only in the grid (Excel's defaults lock every cell;
 * unlocked-cell editing needs xf protection flags the projection lacks), a
 * locked structure blocks sheet add/remove/rename/reorder/hide. The save
 * enforces the same rule, so a replayed draft cannot write past protection.
 */
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import type { WorkbookOperation } from './workbook-draft'

export interface ProtectionState { readonly protected: boolean; readonly hasPassword: boolean }

/** Sheet commands that only navigate, view or copy — allowed on a protected sheet. */
const SHEET_VIEW_COMMANDS = new Set([
  'copy', 'select-all', 'select-range', 'expand-selection', 'move-selection', 'move-selection-enter-tab',
  'scroll-to-cell', 'scroll-view', 'scroll-view-reset', 'set-scroll-relative', 'set-zoom-ratio', 'change-zoom-ratio',
  'set-frozen', 'cancel-frozen', 'set-row-frozen', 'set-col-frozen', 'set-first-row-frozen', 'set-first-column-frozen',
  'set-selection-frozen', 'set-worksheet-activate', 'toggle-gridlines', 'set-once-format-painter', 'set-infinite-format-painter',
  'insert-defined-name', 'remove-defined-name', 'set-defined-name',
])
/** Workbook-structure commands (Excel's Protect Workbook ▸ Structure). */
const STRUCTURE_COMMANDS = new Set([
  'insert-sheet', 'remove-sheet', 'remove-sheet-confirm', 'copy-sheet', 'set-worksheet-name', 'set-worksheet-order',
  'set-worksheet-hidden', 'set-worksheet-show', 'set-tab-color',
])
/** Univer's in-grid permission model never reaches the file. */
const GRID_PERMISSION = /^sheet\.command\.(?:.*-(?:worksheet|range|sheet)-protection(?:-.*)?|set-protection|set-worksheet-permission-points)$/

export const PROTECTED_SHEET_REASON = '工作表受保护，请先在“审阅”中撤销工作表保护'
export const LOCKED_STRUCTURE_REASON = '工作簿结构受保护，请先在“审阅”中撤销工作簿保护'
export const GRID_PERMISSION_REASON = '网格内的区域/工作表权限不会写回文件；请使用“审阅”中的保护工作表'

/** Why a Univer command is refused under the current protection, if it is. */
export function protectionBlockReason(commandId: string, sheetProtected: boolean, structureLocked: boolean): string | undefined {
  if (GRID_PERMISSION.test(commandId)) return GRID_PERMISSION_REASON
  const match = /^sheet\.command\.(.+)$/.exec(commandId)
  if (!match) return undefined
  const name = match[1]!
  if (STRUCTURE_COMMANDS.has(name)) return structureLocked ? LOCKED_STRUCTURE_REASON : undefined
  if (sheetProtected && !SHEET_VIEW_COMMANDS.has(name)) return PROTECTED_SHEET_REASON
  return undefined
}

/** Ribbon commands still available on a protected sheet (view, navigation, copy, protection, structure). */
export const PROTECTED_SHEET_RIBBON = new Set([
  'find', 'print', 'copy', 'note-prev', 'note-next', 'note-show-toggle', 'sheet-protect', 'workbook-protect',
  'toggle-gridlines', 'name-manager-open', 'insert-sheet', 'undo', 'redo',
  'toggle-show-formulas', 'calculate-now', 'calculate-sheet',
])

export interface ProtectionPlan {
  /** before every edit: unprotect sheets (original names) and unlock the structure */
  readonly leading: WorkbookOperation[]
  /** after every edit: protect sheets (final names) and lock the structure */
  readonly trailing: WorkbookOperation[]
  /** final sheet names protected both before and after this session — no edit may target them */
  readonly frozen: ReadonlySet<string>
}

/**
 * `desired` holds toggled sheets by original id (`sheet-N`, as planGridSheets);
 * `names` maps original ids to their final names (absent when removed).
 */
export function planProtection(model: WorkbookModel, desired: ReadonlyMap<string, boolean>, structure: boolean | undefined,
  names: (id: string) => string | undefined): ProtectionPlan {
  const leading: WorkbookOperation[] = [], trailing: WorkbookOperation[] = [], frozen = new Set<string>()
  const originalLock = model.workbookProtection?.lockStructure ?? false
  if (structure === false && originalLock) leading.push({ kind: 'protectWorkbookStructure', lockStructure: false })
  model.sheets.forEach((sheet, index) => {
    const id = `sheet-${index}`, original = sheet.protection?.protected ?? false
    const wanted = desired.get(id) ?? original, finalName = names(id)
    if (original && !wanted) leading.push({ kind: 'protectSheet', sheetName: sheet.name, protect: false })
    if (!finalName) return
    if (!original && wanted) trailing.push({ kind: 'protectSheet', sheetName: finalName, protect: true })
    if (original && wanted) frozen.add(finalName)
  })
  if (structure === true && !originalLock) trailing.push({ kind: 'protectWorkbookStructure', lockStructure: true })
  return { leading, trailing, frozen }
}

/** Save-side enforcement: edits may not target a sheet that stays protected, nor restructure a locked workbook. */
export function assertProtectionRespected(operations: readonly WorkbookOperation[], plan: ProtectionPlan, structureLockedThroughout: boolean): void {
  for (const op of operations) {
    if (op.kind === 'protectSheet' || op.kind === 'protectWorkbookStructure' || op.kind === 'applyPageSetups' || op.kind === 'applyDefinedNames') continue
    if (op.kind === 'applySheetEdits' && structureLockedThroughout) throw new Error(LOCKED_STRUCTURE_REASON)
    const targets = op.kind === 'applyCellEdits'
      ? (op.edits as { sheetName: string }[]).map(edit => edit.sheetName)
      : typeof op.sheetName === 'string' ? [op.sheetName] : []
    const blocked = targets.find(name => plan.frozen.has(name))
    if (blocked) throw new Error(`${PROTECTED_SHEET_REASON}（${blocked}）`)
  }
}
