import { afterEach, expect, it } from 'vitest'
import { Univer, UniverInstanceType, IUniverInstanceService, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsSortPlugin } from '@univerjs/sheets-sort'
import '@univerjs/sheets/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { withWorkbookNotes } from './workbook-notes'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'

// 真实 sheets + sheets-sort 插件（无 mock）：官方 sort-range 在报告工作簿投影
// （含数值单元格类型标记 t 与公式格）上必须真的移动值。渲染层（create-univer
// UI preset）依赖 canvas 2D 上下文，jsdom 不提供，故此处不挂载渲染层；
// 排序命令与数据模型不依赖渲染。
const univers: Univer[] = []
afterEach(() => { for (const item of univers.splice(0)) item.dispose() })

it('real sheets stack: sort-range moves values', async () => {
  const bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1234.567 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 28.125 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 512 } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: null, formula: '=A1*2' } },
  ])
  const model = await readWorkbook(bytes)
  const univer = new Univer({ locale: LocaleType.ZH_CN })
  univers.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverSheetsSortPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookNotes(buildWorkbookData(model, 'probe', 'probe'), model))
  const api = FUniver.newAPI(univer)
  const workbook = api.getActiveWorkbook()!
  const sheet = workbook.getActiveSheet()!
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  expect(sheet.getRange(0, 0, 3, 1).getValues().map(row => row[0])).toEqual([1234.567, 28.125, 512])
  const executed = await api.executeCommand('sheet.command.sort-range', {
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 },
    orderRules: [{ colIndex: 0, type: 'asc' }],
    unitId: workbook.getId(), subUnitId: sheet.getSheetId(), hasTitle: false,
  })
  expect(executed).toBe(true)
  expect(sheet.getRange(0, 0, 3, 1).getValues().map(row => row[0])).toEqual([28.125, 512, 1234.567])
})
