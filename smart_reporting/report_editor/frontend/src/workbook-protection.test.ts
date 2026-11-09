import { expect, it } from 'vitest'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import { GRID_PERMISSION_REASON, LOCKED_STRUCTURE_REASON, PROTECTED_SHEET_REASON, assertProtectionRespected, planProtection, protectionBlockReason } from './workbook-protection'

const model = (sheets: { name: string; protected?: boolean }[], lockStructure?: boolean) => ({
  sheets: sheets.map(sheet => ({ name: sheet.name, ...(sheet.protected === undefined ? {} : { protection: { protected: sheet.protected, hasPassword: false } }) })),
  ...(lockStructure === undefined ? {} : { workbookProtection: { lockStructure, hasPassword: false } }),
}) as unknown as WorkbookModel

it('blocks edits on protected sheets, structure on a locked workbook, and the unsaved grid permission model', () => {
  expect(protectionBlockReason('sheet.command.set-range-values', true, false)).toBe(PROTECTED_SHEET_REASON)
  expect(protectionBlockReason('sheet.command.set-range-values', false, true)).toBeUndefined()
  for (const id of ['sheet.command.copy', 'sheet.command.set-zoom-ratio', 'sheet.command.set-frozen', 'sheet.command.set-worksheet-activate'])
    expect(protectionBlockReason(id, true, false), id).toBeUndefined()
  expect(protectionBlockReason('sheet.command.insert-sheet', true, false)).toBeUndefined()
  expect(protectionBlockReason('sheet.command.set-worksheet-name', false, true)).toBe(LOCKED_STRUCTURE_REASON)
  expect(protectionBlockReason('sheet.command.add-worksheet-protection', false, false)).toBe(GRID_PERMISSION_REASON)
  expect(protectionBlockReason('sheet.command.add-range-protection-from-toolbar', false, false)).toBe(GRID_PERMISSION_REASON)
  expect(protectionBlockReason('univer.command.undo', true, true)).toBeUndefined()
})

it('orders unprotect before and protect after the edits, under original and final names', () => {
  const names: Record<string, string> = { 'sheet-0': 'A', 'sheet-1': 'B2', 'sheet-2': 'C' }
  const plan = planProtection(model([{ name: 'A', protected: true }, { name: 'B' }, { name: 'C', protected: true }], true),
    new Map([['sheet-0', false], ['sheet-1', true]]), false, id => names[id])
  expect(plan.leading).toEqual([{ kind: 'protectWorkbookStructure', lockStructure: false }, { kind: 'protectSheet', sheetName: 'A', protect: false }])
  expect(plan.trailing).toEqual([{ kind: 'protectSheet', sheetName: 'B2', protect: true }])
  expect([...plan.frozen]).toEqual(['C'])
  expect(planProtection(model([{ name: 'A' }]), new Map(), true, () => 'A').trailing).toEqual([{ kind: 'protectWorkbookStructure', lockStructure: true }])
})

it('refuses saving edits into a sheet protected throughout or restructuring a locked workbook', () => {
  const plan = planProtection(model([{ name: 'A', protected: true }, { name: 'B' }]), new Map(), undefined, id => ({ 'sheet-0': 'A', 'sheet-1': 'B' })[id])
  expect(() => assertProtectionRespected([{ kind: 'applyCellEdits', edits: [{ sheetName: 'B' }] }, { kind: 'applyPageSetups', setups: [] }], plan, false)).not.toThrow()
  expect(() => assertProtectionRespected([{ kind: 'applyCellEdits', edits: [{ sheetName: 'A' }] }], plan, false)).toThrow(/撤销工作表保护（A）/)
  expect(() => assertProtectionRespected([{ kind: 'applyRowColumnOps', sheetName: 'A', ops: [] }], plan, false)).toThrow(/受保护/)
  expect(() => assertProtectionRespected([{ kind: 'applySheetEdits', plan: {} }], plan, true)).toThrow(LOCKED_STRUCTURE_REASON)
})
