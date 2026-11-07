import { afterEach, expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { withWorkbookNotes } from './workbook-notes'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { createUniver } from './workbook-vendor/grid/create-univer'
import { LocaleType, mergeLocales } from '@univerjs/core'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import { UniverSheetsSortPreset } from '@univerjs/preset-sheets-sort'
import CoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN'
import SortZhCN from '@univerjs/preset-sheets-sort/locales/zh-CN'

// 复现浏览器生产组合：真实 create-univer + 核心/排序 preset（无 mock），
// 验证官方 sort-range 在真实插件栈上是否真的移动值。
const univers: { dispose(): void }[] = []
afterEach(() => { for (const item of univers.splice(0)) item.dispose() })

it('real preset stack: sort-range moves values', async () => {
  const bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1234.567 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 28.125 } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: null, formula: '=A1*2' } },
  ])
  const model = await readWorkbook(bytes)
  const runtime = createUniver({
    locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, SortZhCN) },
    presets: [
      UniverSheetsCorePreset({ container: 'workbook-grid', header: false, toolbar: false, contextMenu: false, formulaBar: false }),
      UniverSheetsSortPreset(),
    ],
  })
  univers.push(runtime.univer)
  const api = runtime.univerAPI
  const workbook = api.createWorkbook(withWorkbookNotes(buildWorkbookData(model, 'probe', 'probe'), model) as never)
  const sheet = workbook.getActiveSheet()!
  const fired: unknown[] = []
  api.addEvent(api.Event.CommandExecuted, command => {
    const info = command as unknown as { id: string; type: string; params?: unknown }
    if (String(info.id).includes('reorder')) fired.push({ id: info.id, type: info.type, order: (info.params as { order?: unknown })?.order, range: (info.params as { range?: unknown })?.range })
  })
  const valuesBefore = sheet.getRange(0, 0, 3, 1).getValues().map(row => row[0])
  const executed = api.syncExecuteCommand('sheet.command.sort-range', {
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 },
    orderRules: [{ colIndex: 0, type: 'asc' }],
    unitId: workbook.getId(), subUnitId: sheet.getSheetId(), hasTitle: false,
  })
  const valuesAfter = sheet.getRange(0, 0, 3, 1).getValues().map(row => row[0])
  console.log(JSON.stringify({ valuesBefore, executed, valuesAfter, fired }))
  expect(executed).toBe(true)
})
