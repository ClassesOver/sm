import { afterEach, expect, it, vi } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Univer, UniverInstanceType, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { geometryChanges } from './workbook-vendor/core/data-tools'
import { AUTOFIT_COMMANDS, AXIS_LIMITS, applyAxisSize, autofitSpans, captureAxisTarget, createAxisSizeDialog, parseAxisSize } from './workbook-axis-size'
import { mountWorkbookRibbon } from './workbook-ribbon'
import { independentPython } from './test-independent-python'

const univers: Univer[] = []
afterEach(() => { univers.splice(0).forEach(univer => univer.dispose()); document.body.replaceChildren() })

it('parses file units with a decimal comma and enforces the persisted ranges', () => {
  expect(parseAxisSize('row', ' 22,5 ')).toBe(22.5)
  expect(parseAxisSize('col', '12.345')).toBe(12.35)
  expect(AXIS_LIMITS.row.max).toBe(409)
  for (const [axis, raw] of [['row', '0'], ['row', '409.5'], ['col', '0.5'], ['col', '256'], ['col', ''], ['row', 'abc']] as const) {
    expect(() => parseAxisSize(axis, raw), `${axis}:${raw}`).toThrow(axis === 'row' ? '行高' : '列宽')
  }
})

it('applies row heights and column widths to the selection on real Univer and persists them to the XLSX', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'A' } },
    { sheetName: 'Sheet1', row: 3, column: 3, writeValue: true, cell: { value: 'D' } },
  ])
  const model = await readWorkbook(source)
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  univers.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'axis', 'axis'))
  const workbook = FUniver.newAPI(univer).getActiveWorkbook()!
  const sheet = workbook.getActiveSheet()
  let selected = sheet.getRange(1, 0, 2, 2) // rows 2-3, columns A-B
  const facade = { getActiveSheet: () => Object.assign(Object.create(sheet), { getSelection: () => ({ getActiveRange: () => selected }) }), getSheetBySheetId: (id: string) => workbook.getSheetBySheetId(id) }
  expect(geometryChanges(model, readBackSnapshot(workbook.getSnapshot()))).toEqual({ columns: [], rows: [] })
  const rowTarget = captureAxisTarget(facade as never, 'row')!
  expect(rowTarget).toMatchObject({ axis: 'row', start: 1, count: 2 })
  // 打开对话框后选区变化不影响已冻结的目标。
  selected = sheet.getRange(3, 3, 1, 1)
  applyAxisSize(rowTarget, facade as never, 30, true)
  const colTarget = captureAxisTarget(facade as never, 'col')!
  expect(colTarget).toMatchObject({ axis: 'col', start: 3, count: 1 })
  applyAxisSize(colTarget, facade as never, 20, true)
  expect(() => applyAxisSize(colTarget, facade as never, 20, false)).toThrow('不可编辑')
  const geometry = geometryChanges(model, readBackSnapshot(workbook.getSnapshot()))
  expect(geometry.rows.map(row => [row.index, row.heightPoints])).toEqual([[1, 30], [2, 30]])
  expect(geometry.columns.map(column => [column.index, Math.round(column.widthChars * 100) / 100])).toEqual([[3, 20]])
  const operations = [
    ...geometry.columns.map(change => ({ kind: 'applyColumnWidths' as const, sheetName: change.sheet, entries: [{ index: change.index, widthChars: change.widthChars }] })),
    ...geometry.rows.map(change => ({ kind: 'applyRowHeights' as const, sheetName: change.sheet, entries: [{ index: change.index, heightPoints: change.heightPoints }] })),
  ]
  const bytes = await applyWorkbookOperations(source, operations)
  const file = join(await mkdtemp(join(tmpdir(), 'xlsx-axis-')), 'axis.xlsx')
  await writeFile(file, bytes)
  const checked = spawnSync(independentPython(), ['-I', '-c', "import json,openpyxl,sys; s=openpyxl.load_workbook(sys.argv[1]).active; print(json.dumps({'rows': [s.row_dimensions[i].height for i in (1,2,3,4)], 'width': round(s.column_dimensions['D'].width, 2), 'A': s['A1'].value, 'D': s['D4'].value}))", file], { encoding: 'utf8' })
  expect(checked.status, checked.stderr).toBe(0)
  expect(JSON.parse(checked.stdout)).toEqual({ rows: [null, 30, 30, null], width: 20, A: 'A', D: 'D' })
})

it('opens the dialog from enabled ribbon commands and applies only a valid value to the captured target', () => {
  const host = document.createElement('div'); document.body.append(host)
  const command = vi.fn()
  const ribbon = mountWorkbookRibbon(host, command, { rotation: () => 0, editable: () => true, hasSelection: () => true })
  host.querySelector<HTMLButtonElement>('[role="tab"][data-ribbon-tab="Home"]')!.click()
  for (const id of ['row-height-open', 'col-width-open']) {
    const button = host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled, id).toBe(false); expect(button.dataset.unavailableReason, id).toBeUndefined()
    button.click()
  }
  expect(command.mock.calls.map(call => call[0])).toEqual(['row-height-open', 'col-width-open'])
  ribbon.dispose()
  const apply = vi.fn()
  const dialog = createAxisSizeDialog(document.body, apply)
  dialog.open({ axis: 'col', start: 2, count: 3 })
  const input = document.querySelector<HTMLInputElement>('.workbook-ribbon-axis-value')!
  expect(document.querySelector('.workbook-ribbon-axis-help')!.textContent).toContain('3 列')
  input.value = '300'; document.querySelector('.workbook-ribbon-axis-dialog form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).not.toHaveBeenCalled(); expect(input.getAttribute('aria-invalid')).toBe('true')
  input.value = '18,5'; document.querySelector('.workbook-ribbon-axis-dialog form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledExactlyOnceWith({ axis: 'col', start: 2, count: 3 }, 18.5)
  dialog.dispose()
})

it('projects file widths, heights and hidden rows with Univer snapshot keys and diffs nothing when untouched', async () => {
  // 回归：sheets-web 迁移来的加载器曾写 width/height/hidden（Univer 不识别），文件几何不显示、
  // 网格改动也回读不到。现写 w/h/hd，回读同键。
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'head' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'hide me' } },
  ])
  bytes = await applyWorkbookOperations(bytes, [
    { kind: 'applyColumnWidths', sheetName: 'Sheet1', entries: [{ index: 1, widthChars: 30 }] },
    { kind: 'applyRowHeights', sheetName: 'Sheet1', entries: [{ index: 0, heightPoints: 45 }] },
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, values: ['head'] }] }, hiddenRows: [1] },
  ])
  const model = await readWorkbook(bytes)
  const data = buildWorkbookData(model, 'geo', 'geo')
  const sheetData = data.sheets[data.sheetOrder[0]!]!
  expect(sheetData.columnData![1]).toMatchObject({ w: 30 * 7 + 5 })
  expect(sheetData.rowData![0]).toMatchObject({ h: 60, ia: 0 })
  expect(sheetData.rowData![1]).toMatchObject({ hd: 1 })
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  univers.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, data)
  const workbook = FUniver.newAPI(univer).getActiveWorkbook()!
  const sheet = workbook.getActiveSheet()
  expect(sheet.getColumnWidth(1)).toBe(215)
  expect(sheet.getRowHeight(0)).toBe(60)
  expect(sheet.getSheet().getRowRawVisible(1)).toBe(false)
  expect(sheet.getSheet().getRowRawVisible(0)).toBe(true)
  expect(geometryChanges(model, readBackSnapshot(workbook.getSnapshot()))).toEqual({ columns: [], rows: [] })
})

it('AutoFit Row Height resets only rows the file sized and saves them as automatic', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'tall' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'plain' } },
  ])
  bytes = await applyWorkbookOperations(bytes, [{ kind: 'applyRowHeights', sheetName: 'Sheet1', entries: [{ index: 0, heightPoints: 45 }, { index: 4, heightPoints: 30 }] }])
  const model = await readWorkbook(bytes)
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  univers.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'auto', 'auto'))
  const api = FUniver.newAPI(univer)
  const workbook = api.getActiveWorkbook()!
  const sheet = workbook.getActiveSheet()
  // 选区 A1:B3 → 整行 1–3（固定源 fullRowSpans）；行 5 不在选区内保持原高。
  const ranges = autofitSpans('row', { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, sheet.getMaxRows(), sheet.getMaxColumns())
  expect(ranges).toEqual([{ startRow: 0, endRow: 2, startColumn: 0, endColumn: sheet.getMaxColumns() - 1 }])
  expect(await api.executeCommand(AUTOFIT_COMMANDS.row, { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), ranges })).toBe(true)
  const geometry = geometryChanges(model, readBackSnapshot(workbook.getSnapshot()))
  expect(geometry.rows).toEqual([{ sheet: 'Sheet1', index: 0, heightPoints: null }])
  const saved = await applyWorkbookOperations(bytes, geometry.rows.map(change => ({ kind: 'applyRowHeights' as const, sheetName: change.sheet, entries: [{ index: change.index, heightPoints: change.heightPoints }] })))
  const file = join(await mkdtemp(join(tmpdir(), 'xlsx-autofit-')), 'autofit.xlsx')
  await writeFile(file, saved)
  const checked = spawnSync(independentPython(), ['-I', '-c', "import json,openpyxl,sys; s=openpyxl.load_workbook(sys.argv[1]).active; print(json.dumps({'h1': s.row_dimensions[1].height, 'c1': s.row_dimensions[1].customHeight, 'h5': s.row_dimensions[5].height, 'a1': s['A1'].value}))", file], { encoding: 'utf8' })
  expect(checked.status, checked.stderr).toBe(0)
  expect(JSON.parse(checked.stdout)).toEqual({ h1: null, c1: false, h5: 30, a1: 'tall' })
})

it('AutoFit Column Width targets whole columns of the selection with the official command', () => {
  expect(AUTOFIT_COMMANDS.col).toBe('sheet.command.set-col-auto-width')
  expect(autofitSpans('col', { startRow: 3, endRow: 5, startColumn: 1, endColumn: 2 }, 1000, 26)).toEqual([{ startRow: 0, endRow: 999, startColumn: 1, endColumn: 2 }])
  const host = document.createElement('div'); document.body.append(host)
  const command = vi.fn()
  const ribbon = mountWorkbookRibbon(host, command, { rotation: () => 0, editable: () => true, hasSelection: () => true })
  host.querySelector<HTMLButtonElement>('[role="tab"][data-ribbon-tab="Home"]')!.click()
  for (const id of ['autofit-row-height', 'autofit-col-width']) {
    const button = host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled, id).toBe(false); button.click()
  }
  expect(command.mock.calls.map(call => call[0])).toEqual(['autofit-row-height', 'autofit-col-width'])
  ribbon.dispose()
})
