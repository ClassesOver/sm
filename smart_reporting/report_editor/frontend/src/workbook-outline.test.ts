import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
const implementation = './workbook-outline'
async function product(): Promise<any> {
  return import(/* @vite-ignore */ implementation)
}
async function setup() {
  const model = await readWorkbook(await createBlankWorkbook())
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin)
  const api = FUniver.newAPI(univer),
    workbook = api.createWorkbook(buildWorkbookData(model, 'outline', 'Outline') as any)
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  return { model, univer, api, workbook, sheet: workbook.getActiveSheet()!, runtime: { univer, univerAPI: api } }
}
it('groups real rows and columns, folds innermost detail and exports outline metadata in the actual ZIP', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline, workbookOutlineOperations } = await product()
    c.sheet.getRange('A2:B5').activate()
    expect(applyWorkbookOutline(c.runtime, 'group', 'rows').changed).toBe(true)
    c.sheet.getRange('A3:B4').activate()
    applyWorkbookOutline(c.runtime, 'group', 'rows')
    applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    expect(c.sheet.getSheet().getRowVisible(2)).toBe(false)
    expect(c.sheet.getSheet().getRowVisible(1)).toBe(true)
    c.sheet.getRange('C1:D2').activate()
    applyWorkbookOutline(c.runtime, 'group', 'cols')
    applyWorkbookOutline(c.runtime, 'hide-detail', 'cols')
    const ops = workbookOutlineOperations(c.model, c.workbook)
    const saved = await applyWorkbookOperations(await createBlankWorkbook(), ops),
      reopened = await readWorkbook(saved)
    expect(reopened.sheets[0]!.rows.find((r) => r.row === 3)).toMatchObject({ outlineLevel: 2, hidden: true })
    expect(reopened.sheets[0]!.columns.find((col) => col.start === 3)).toMatchObject({ outlineLevel: 1, hidden: true })
    expect(reopened.sheets[0]!.columns.find((col) => col.start === 5)).toMatchObject({ collapsed: true })
  } finally {
    c.univer.dispose()
  }
})
it('native outline metadata follows insert/delete and move with other custom and folded summaries intact', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline, installWorkbookOutline } = await product()
    const lifecycle = installWorkbookOutline(c.runtime)
    try {
      c.sheet.getRange('A2:A5').activate()
      applyWorkbookOutline(c.runtime, 'group', 'rows')
      const manager = c.sheet.getSheet().getRowManager()
      manager.setCustomMetadata(2, { ...manager.getCustomMetadata(2), other: 'retained' })
      c.sheet.getRange('A2:A5').activate()
      applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
      c.sheet.insertRows(3, 1)
      expect(manager.getCustomMetadata(3)?.genofficeOutline.level).toBe(1)
      expect(manager.getCustomMetadata(6)?.genofficeOutline.collapsed).toBe(true)
      expect(manager.getCustomMetadata(2)?.other).toBe('retained')
      c.sheet.deleteRows(3, 1)
      expect(manager.getCustomMetadata(5)?.genofficeOutline.collapsed).toBe(true)
      await c.api.undo()
      expect(manager.getCustomMetadata(6)?.genofficeOutline.collapsed).toBe(true)
      const beforeMove = structuredClone(c.workbook.getSnapshot())
      c.sheet.moveRows(c.sheet.getRange('A3:A3'), 9)
      const moved = Object.entries(manager.getRowData()).find(([, v]: any) => v?.custom?.other === 'retained')
      expect(Number(moved?.[0])).not.toBe(2)
      expect((moved?.[1] as any)?.custom.genofficeOutline.level).toBe(1)
      expect(
        Object.values(manager.getRowData()).filter((v: any) => v?.custom?.genofficeOutline?.collapsed)
      ).toHaveLength(1)
      await c.api.undo()
      expect(c.workbook.getSnapshot().sheets[c.sheet.getSheetId()]!.rowData).toEqual(
        beforeMove.sheets[c.sheet.getSheetId()]!.rowData
      )
    } finally {
      lifecycle.dispose()
    }
  } finally {
    c.univer.dispose()
  }
})
it('keeps explicitly folded nested groups on outer expand and mirrors source hidden-only undo', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline } = await product()
    c.sheet.getRange('A2:A7').activate()
    applyWorkbookOutline(c.runtime, 'group', 'rows')
    c.sheet.getRange('A3:A4').activate()
    applyWorkbookOutline(c.runtime, 'group', 'rows')
    applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    c.sheet.getRange('A7').activate()
    applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    c.sheet.getRange('A8').activate()
    applyWorkbookOutline(c.runtime, 'show-detail', 'rows')
    expect(c.sheet.getSheet().getRowVisible(1)).toBe(true)
    expect(c.sheet.getSheet().getRowVisible(2)).toBe(false)
    expect(c.sheet.getSheet().getRowVisible(5)).toBe(true)
    await c.api.undo()
    expect(c.sheet.getSheet().getRowManager().getCustomMetadata(7)?.genofficeOutline.collapsed).toBe(false)
    c.sheet.getRange('A1').activate()
    expect(applyWorkbookOutline(c.runtime, 'clear').changed).toBe(true)
    expect(c.sheet.getSheet().getRowVisible(2)).toBe(true)
    expect(c.sheet.getSheet().getRowManager().getCustomMetadata(2)?.genofficeOutline.level).toBe(0)
  } finally {
    c.univer.dispose()
  }
})
it('uses source auto-axis and max depth, supports ungroup and refuses protected sheets', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline } = await product()
    c.sheet.getRange(0, 1, c.sheet.getMaxRows(), 2).activate()
    for (let i = 0; i < 7; i++) expect(applyWorkbookOutline(c.runtime, 'group').changed).toBe(true)
    expect(applyWorkbookOutline(c.runtime, 'group').changed).toBe(false)
    expect(c.sheet.getSheet().getColumnManager().getCustomMetadata(1)?.genofficeOutline.level).toBe(7)
    expect(() => applyWorkbookOutline(c.runtime, 'ungroup', 'cols', () => true)).toThrow('保护')
    applyWorkbookOutline(c.runtime, 'ungroup', 'cols')
    expect(c.sheet.getSheet().getColumnManager().getCustomMetadata(1)?.genofficeOutline.level).toBe(6)
  } finally {
    c.univer.dispose()
  }
})
it('imports summary-before metadata and folds from a summary line at row zero', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline } = await product()
    c.sheet
      .getSheet()
      .setCustomMetadata({ genofficeOutline: { summaryBelow: false, summaryRight: false }, other: 'sheet' })
    c.sheet.getRange('A2:A3').activate()
    applyWorkbookOutline(c.runtime, 'group', 'rows')
    c.sheet.getRange('A1').activate()
    applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    expect(c.sheet.getSheet().getRowVisible(1)).toBe(false)
    expect(c.sheet.getSheet().getRowManager().getCustomMetadata(0)?.genofficeOutline.collapsed).toBe(true)
    expect(c.sheet.getSheet().getCustomMetadata()?.other).toBe('sheet')
  } finally {
    c.univer.dispose()
  }
})
it('projects existing distant outline metadata and summary-before settings through a real ZIP reload', async () => {
  const { applySheetOutline } = await import('@sheets-web/xlsx-engine')
  const model = await readWorkbook(
    await applySheetOutline(await createBlankWorkbook(), 'Sheet1', {
      rows: [{ index: 1100, level: 1, collapsed: false }],
      columns: [{ index: 300, level: 1, collapsed: false }]
    })
  )
  const config = buildWorkbookData(model, 'import-outline', 'Outline')
  const projected = config.sheets[config.sheetOrder[0]!]!
  expect(projected.rowCount).toBeGreaterThan(1100)
  expect(projected.columnCount).toBeGreaterThan(300)
  expect(projected.rowData?.[1100]?.custom?.genofficeOutline).toEqual({ level: 1, collapsed: false })
  expect(projected.columnData?.[300]?.custom?.genofficeOutline).toEqual({ level: 1, collapsed: false })
})
it('composes raw outline visibility with filter cache after the outline operation without losing hidden rows', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline, workbookOutlineOperations } = await product()
    const { workbookFilterOperations } = await import('./workbook-filters')
    c.sheet.getRange('A3:A4').activate()
    applyWorkbookOutline(c.runtime, 'group', 'rows')
    applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    const filter = {
      getRange: () => ({ getRow: () => 0, getColumn: () => 0, getHeight: () => 10, getWidth: () => 1 }),
      getColumnFilterCriteria: () => ({ filters: { filters: ['keep'] } }),
      getFilteredOutRows: () => [1]
    }
    const filters = workbookFilterOperations(c.model, {
      getSnapshot: () => c.workbook.getSnapshot(),
      getSheets: () => [{ getSheetId: () => c.sheet.getSheetId(), getSheetName: () => c.sheet.getSheetName(), getFilter: () => filter }]
    } as any)
    const saved = await applyWorkbookOperations(await createBlankWorkbook(), [...workbookOutlineOperations(c.model, c.workbook), ...filters])
    const reopened = await readWorkbook(saved)
    expect(reopened.sheets[0]!.rows.filter(row => row.hidden).map(row => row.row)).toEqual([2, 3, 4])
    c.sheet.getRange('A5').activate()
    applyWorkbookOutline(c.runtime, 'show-detail', 'rows')
    expect(c.sheet.getSheet().getRowRawVisible(2)).toBe(true)
  } finally { c.univer.dispose() }
})
it('does not turn a restored ungrouped gap into grouped detail when undoing a row deletion', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline, installWorkbookOutline } = await product()
    const lifecycle = installWorkbookOutline(c.runtime)
    try {
      c.sheet.getRange('A2:A4').activate(); applyWorkbookOutline(c.runtime, 'group', 'rows')
      c.sheet.getRange('A3').activate(); applyWorkbookOutline(c.runtime, 'ungroup', 'rows')
      c.sheet.deleteRows(2, 1)
      await c.api.undo()
      expect(c.sheet.getSheet().getRowManager().getCustomMetadata(2)?.genofficeOutline.level).toBe(0)
    } finally { lifecycle.dispose() }
  } finally { c.univer.dispose() }
})
it('keeps a source gap with no outline custom metadata ungrouped after delete and undo', async () => {
  const c = await setup()
  try {
    const { applyWorkbookOutline, installWorkbookOutline } = await product()
    const lifecycle = installWorkbookOutline(c.runtime)
    try {
      c.sheet.getRange('A2').activate(); applyWorkbookOutline(c.runtime, 'group', 'rows')
      c.sheet.getRange('A4').activate(); applyWorkbookOutline(c.runtime, 'group', 'rows')
      expect(c.sheet.getSheet().getRowManager().getCustomMetadata(2)).toBeUndefined()
      c.sheet.deleteRows(2, 1)
      await c.api.undo()
      expect(c.sheet.getSheet().getRowManager().getCustomMetadata(2)?.genofficeOutline?.level ?? 0).toBe(0)
    } finally { lifecycle.dispose() }
  } finally { c.univer.dispose() }
})
it('persists summary settings through strict bridge and actual ZIP while preserving unrelated sheet metadata', async () => {
  const c = await setup()
  try {
    const p = await product()
    c.sheet.getSheet().setCustomMetadata({ other: 'kept' })
    expect(p.setWorkbookOutlineSummary(c.runtime, { below: false, right: false }).changed).toBe(true)
    expect(p.readWorkbookOutline(c.sheet)).toMatchObject({ summaryBelow: false, summaryRight: false })
    expect(c.sheet.getSheet().getCustomMetadata()?.other).toBe('kept')
    const ops = p.workbookOutlineOperations(c.model, c.workbook)
    expect(ops).toHaveLength(1)
    expect(ops[0]).toMatchObject({ summaryBelow: false, summaryRight: false })
    const saved = await applyWorkbookOperations(await createBlankWorkbook(), ops)
    const reopened = await readWorkbook(saved)
    expect(reopened.sheets[0]).toMatchObject({ outlineSummaryBelow: false, outlineSummaryRight: false })
    expect(() => p.setWorkbookOutlineSummary(c.runtime, { below: true }, () => true)).toThrow('保护')
    expect(p.setWorkbookOutlineSummary(c.runtime, { below: false }).changed).toBe(false)
  } finally { c.univer.dispose() }
})
it('uses exact gutter group identity, real hidden state and level buttons with nested folds', async () => {
  const c = await setup()
  try {
    const p = await product()
    c.sheet.getRange('A2:A7').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'rows')
    c.sheet.getRange('A3:A4').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'rows')
    const [outer, inner] = p.workbookOutlineGroups(c.sheet, 'rows')
    const version = p.readWorkbookOutline(c.sheet).version
    p.toggleWorkbookOutlineGroup(c.runtime, 'rows', inner, true)
    p.toggleWorkbookOutlineGroup(c.runtime, 'rows', outer, true)
    expect(p.workbookOutlineGroups(c.sheet, 'rows')[0]).toMatchObject({ collapsed: true, folded: true })
    p.toggleWorkbookOutlineGroup(c.runtime, 'rows', outer, false)
    expect(c.sheet.getSheet().getRowRawVisible(1)).toBe(true)
    expect(c.sheet.getSheet().getRowRawVisible(2)).toBe(false)
    expect(p.readWorkbookOutline(c.sheet).version).not.toBe(version)
    expect(p.toggleWorkbookOutlineGroup(c.runtime, 'rows', { ...inner, end: 99 }, true).changed).toBe(false)
    p.showWorkbookOutlineLevel(c.runtime, 'rows', 2)
    expect(c.sheet.getSheet().getRowRawVisible(1)).toBe(true)
    expect(c.sheet.getSheet().getRowRawVisible(2)).toBe(false)
    p.showWorkbookOutlineLevel(c.runtime, 'rows', 3)
    expect(c.sheet.getSheet().getRowRawVisible(2)).toBe(true)
    expect(p.workbookOutlineGroups(c.sheet, 'rows').every((g: any) => !g.folded && !g.collapsed)).toBe(true)
    expect(() => p.showWorkbookOutlineLevel(c.runtime, 'rows', 1, () => true)).toThrow('保护')
  } finally { c.univer.dispose() }
})
it('keeps prior folded summary flags when changing direction and handles boundary/shared-summary level guards', async () => {
  const c = await setup()
  try {
    const p = await product()
    c.sheet.getRange('A2:A4').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'rows')
    c.sheet.getRange('A3:A4').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'rows')
    p.showWorkbookOutlineLevel(c.runtime, 'rows', 2)
    expect(c.sheet.getSheet().getRowManager().getCustomMetadata(4)?.genofficeOutline.collapsed).toBe(false)
    p.applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    const prior = structuredClone(c.sheet.getSheet().getRowManager().getCustomMetadata(4))
    p.setWorkbookOutlineSummary(c.runtime, { below: false })
    expect(p.readWorkbookOutline(c.sheet)).toMatchObject({ summaryBelow: false, summaryRight: true })
    expect(c.sheet.getSheet().getRowManager().getCustomMetadata(4)).toEqual(prior)
    expect(p.workbookOutlineGroups(c.sheet, 'rows')[0].summary).toBe(0)
    c.sheet.getRange('B1:B2').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'cols')
    expect(p.toggleWorkbookOutlineGroup(c.runtime, 'cols', p.workbookOutlineGroups(c.sheet, 'cols')[0], true).changed).toBe(true)
    p.setWorkbookOutlineSummary(c.runtime, { right: false })
    expect(p.workbookOutlineGroups(c.sheet, 'cols')[0].summary).toBe(0)
    expect(p.showWorkbookOutlineLevel(c.runtime, 'cols', 0).changed).toBe(false)
    expect(p.showWorkbookOutlineLevel(c.runtime, 'cols', 9).changed).toBe(false)
    c.sheet.getRange('A1:A2').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'rows')
    const boundary = p.workbookOutlineGroups(c.sheet, 'rows').find((g: any) => g.summary === -1)
    expect(p.toggleWorkbookOutlineGroup(c.runtime, 'rows', boundary, true).changed).toBe(true)
    expect(c.sheet.getSheet().getRowManager().getCustomMetadata(-1)).toBeUndefined()
  } finally { c.univer.dispose() }
})
it('clears the entire outline when the active selection is absent like the source clear action', async () => {
  const c = await setup()
  try {
    const p = await product()
    c.sheet.getRange('A2:A4').activate()
    p.applyWorkbookOutline(c.runtime, 'group', 'rows')
    p.applyWorkbookOutline(c.runtime, 'hide-detail', 'rows')
    const runtime = { univerAPI: { getActiveWorkbook: () => ({ getActiveSheet: () => c.sheet, getActiveRange: () => null }) } }
    expect(p.applyWorkbookOutline(runtime, 'clear').changed).toBe(true)
    expect(p.workbookOutlineGroups(c.sheet, 'rows')).toEqual([])
    expect(c.sheet.getSheet().getRowRawVisible(1)).toBe(true)
    expect(() => p.applyWorkbookOutline(runtime, 'group')).toThrow('选择')
  } finally { c.univer.dispose() }
})

it('reads outline summary settings without scanning row or column metadata', async () => {
  const c = await setup()
  try {
    const { readWorkbookOutlineSummary } = await product()
    const native = c.sheet.getSheet(), rows = vi.spyOn(native.getRowManager(), 'getRowData'), cols = vi.spyOn(native.getColumnManager(), 'getColumnData')
    expect(readWorkbookOutlineSummary(c.sheet)).toEqual({summaryBelow:true,summaryRight:true})
    native.setCustomMetadata({genofficeOutline:{summaryBelow:false,summaryRight:false}})
    expect(readWorkbookOutlineSummary(c.sheet)).toEqual({summaryBelow:false,summaryRight:false})
    expect(rows).not.toHaveBeenCalled();expect(cols).not.toHaveBeenCalled()
  } finally {c.univer.dispose()}
})
