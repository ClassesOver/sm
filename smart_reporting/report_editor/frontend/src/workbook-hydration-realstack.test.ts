import { afterEach, expect, it } from 'vitest'
import { applyCellEdits, applyPageSetups, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { withWorkbookFilters, workbookFilterOperations, type FilterWorkbook } from './workbook-filters'
import { withWorkbookNotes } from './workbook-notes'
import { withWorkbookView } from './workbook-view'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { Univer, UniverInstanceType, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsFilterPlugin } from '@univerjs/sheets-filter'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-filter/facade'

// 真实 Univer sheets + sheets-filter 插件（无 facade 替身、无渲染层）：源筛选、缩放、网格线
// 必须在加载时灌入网格，保存无关修改时差分不得把它们当作"已移除/改回默认"。
const univers: { dispose(): void }[] = []
afterEach(() => { for (const item of univers.splice(0)) item.dispose() })

const sourceModel = async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: '部门' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: '乙' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: '甲' } },
  ])
  // 筛选范围从 B 列开始：引擎 colId 是偏移 0，Univer 内部是绝对列 1。
  bytes = await applyWorkbookOperations(bytes, [{ kind: 'applySheetFilter', sheetName: 'Sheet1',
    filter: { range: { startRow: 0, endRow: 2, startColumn: 1, endColumn: 1 }, columns: [{ colId: 0, values: ['乙'] }] }, hiddenRows: [2] }])
  bytes = await applyPageSetups(bytes, [{ sheetName: 'Sheet1', zoomScale: 150, showGridlines: false }])
  return readWorkbook(bytes)
}

const mount = (model: Awaited<ReturnType<typeof sourceModel>>, hydrate: boolean) => {
  const univer = new Univer({ locale: LocaleType.ZH_CN })
  univers.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverSheetsFilterPlugin)
  const data = withWorkbookNotes(buildWorkbookData(model, 'probe', 'probe'), model)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, hydrate ? withWorkbookView(withWorkbookFilters(data, model), model) : data)
  return FUniver.newAPI(univer).getActiveWorkbook()!
}

it('source filter, zoom and gridlines are hydrated so an unrelated save emits no filter/view change', async () => {
  const model = await sourceModel()
  expect(model.sheets[0]!.filter?.range).toMatchObject({ startColumn: 1 })
  expect(model.sheets[0]!.zoomScale).toBe(150)
  expect(model.sheets[0]!.showGridlines).toBe(false)

  // 反例：未灌入时网格没有筛选，差分把源筛选误判为移除（Codex P1 的原始场景）。
  const bare = mount(model, false)
  expect(bare.getActiveSheet().getFilter()).toBeNull()
  expect(workbookFilterOperations(model, bare as unknown as FilterWorkbook)).toEqual([{ kind: 'applySheetFilter', sheetName: 'Sheet1', filter: null }])
  // sheets-ui 的 FWorksheet.getZoom() 即 Worksheet.getZoomRatio()（无渲染层时直接读）。
  expect(bare.getActiveSheet().getSheet().getZoomRatio()).toBe(1)
  expect(bare.getActiveSheet().hasHiddenGridLines()).toBe(false)
  univers.splice(0).forEach(item => item.dispose())

  const workbook = mount(model, true)
  const sheet = workbook.getActiveSheet()
  const filter = sheet.getFilter()!
  expect(filter).not.toBeNull()
  expect(filter.getColumnFilterCriteria(1)).toMatchObject({ colId: 1, filters: { filters: ['乙'] } })
  expect(filter.getFilteredOutRows()).toEqual([2])
  expect(workbookFilterOperations(model, workbook as unknown as FilterWorkbook)).toEqual([])
  expect(Math.round(sheet.getSheet().getZoomRatio() * 100)).toBe(150)
  expect(sheet.hasHiddenGridLines()).toBe(true)

  // 用户真实改了条件：差分写回偏移 colId 0（不是 facade 返回的绝对列 1）。
  filter.setColumnFilterCriteria(1, { colId: 1, filters: { filters: ['甲'] } })
  const [operation] = workbookFilterOperations(model, workbook as unknown as FilterWorkbook)
  expect(operation).toMatchObject({ kind: 'applySheetFilter', filter: { range: { startColumn: 1, endColumn: 1 }, columns: [{ colId: 0, values: ['甲'] }] } })
})
