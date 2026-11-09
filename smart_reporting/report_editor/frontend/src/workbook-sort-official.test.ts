import { afterEach, beforeEach, expect, it } from 'vitest'
import { Univer, UniverInstanceType, ICommandService, IUniverInstanceService, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsNotePlugin } from '@univerjs/sheets-note'
import { UniverSheetsSortPlugin } from '@univerjs/sheets-sort'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-note/facade'
import { applyCellEdits, applySheetNotes, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { withWorkbookNotes } from './workbook-notes'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'

// 固定事实（Univer 0.25.1 实测，2026-11-06）：
// 1) FRange 无 sort facade 方法；官方入口是 sheet.command.sort-range，
//    参数 {range, orderRules:[{colIndex(绝对列), type:'asc'|'desc'}], unitId, subUnitId, hasTitle}。
// 2) 排序后批注随行迁移（reorder-range → ref-range controller），
//    且迁移走 silent+onlyLocal 的 update-note-position（与行列插删同链路）。
// 3) 因此官方排序在网格内是批注安全的；保存侧作者保留需引擎补移动语义后方可在 main 放行。

const instances: Univer[] = []
const probe: { bytes?: Uint8Array; model?: Awaited<ReturnType<typeof readWorkbook>> } = {}
afterEach(() => { instances.splice(0).forEach(univer => univer.dispose()) })
beforeEach(async () => {
  const bytes = await applySheetNotes(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'c-alpha' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a-beta' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'b-gamma' } },
  ]), 'Sheet1', [
    { row: 0, column: 0, author: 'Alice', text: 'note-on-c-alpha' },
    { row: 2, column: 0, author: 'Bob', text: 'note-on-b-gamma' },
  ])
  probe.bytes = bytes
  probe.model = await readWorkbook(bytes)
})

it('official sort-range sorts ascending and migrates notes with their rows', async () => {
  const bytes = probe.bytes!
  const model = probe.model!
  const univer = new Univer({ locale: LocaleType.ZH_CN })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverSheetsNotePlugin)
  univer.registerPlugin(UniverSheetsSortPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookNotes(buildWorkbookData(model, 'probe', 'probe'), model))
  const api = FUniver.newAPI(univer)
  const workbook = api.getActiveWorkbook()!
  const sheet = workbook.getActiveSheet()!
  const commands = univer.__getInjector().get(ICommandService)
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  expect(sheet.getRange(0, 0).getNote()?.note).toBe('note-on-c-alpha')
  const executed = commands.syncExecuteCommand('sheet.command.sort-range', {
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 },
    orderRules: [{ colIndex: 0, type: 'asc' }],
    unitId: workbook.getId(), subUnitId: sheet.getSheetId(), hasTitle: false,
  })
  expect(executed).toBe(true)
  expect(sheet.getRange(0, 0, 3, 1).getValues().map(row => row[0])).toEqual(['a-beta', 'b-gamma', 'c-alpha'])
  const notes = new Map(sheet.getNotes().map(note => [note.note, { row: note.row, col: note.col }]))
  expect(notes.get('note-on-c-alpha')).toEqual({ row: 2, col: 0 })
  expect(notes.get('note-on-b-gamma')).toEqual({ row: 1, col: 0 })
  // 原始源文件不受网格内排序影响（保存前）。
  expect((await readWorkbook(bytes)).sheets[0]!.notes!.notes.map(note => note.row)).toEqual([0, 2])
})
