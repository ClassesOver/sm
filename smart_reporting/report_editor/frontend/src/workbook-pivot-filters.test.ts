import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, editPivotPlan, readWorkbookPivots } from './workbook-pivot'
import { readPivotFilterFields, pivotMemberFilterConfig, pivotTimelineFilterConfig } from './workbook-pivot-filters'

async function fixture(numericDates = false) {
  const rows = [['地区', '日期', '收入'], ['东', numericDates ? 45292 : '2024-01-01', 10], ['西', numericDates ? 45293 : '2024-01-02', 20], ['北', numericDates ? 45294 : '2024-01-03', 30]]
  const source = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value }, ...(numericDates && c === 1 && r > 0 ? { style: { numberFormat: 'yyyy-mm-dd' } } : {}) }))))
  const config = { name: '收入分析', sourceSheetName: 'Sheet1', sourceRange: 'A1:C4', targetSheetName: 'Sheet1', targetCell: 'F1', rowFields: ['地区'], columnFields: ['日期'], values: [{ field: '收入', agg: 'sum' as const }] }
  const bytes = await applyWorkbookOperations(source, (await createPivotPlan(source, config)).operations)
  return { bytes, pivot: (await readWorkbookPivots(bytes))[0]! }
}

it('saves member selection and reopens the actual pivot result without creating slicer parts', async () => {
  const { bytes, pivot } = await fixture(), fields = await readPivotFilterFields(bytes, pivot)
  const config = pivotMemberFilterConfig(pivot, fields, '地区', ['东', '北'])
  const plan = await editPivotPlan(bytes, pivot.tablePath, config), saved = await applyWorkbookOperations(bytes, plan.operations)
  const reopened = (await readWorkbookPivots(saved))[0]!, output = (await readWorkbook(saved)).sheets[0]!
  expect(reopened.hiddenMembers?.row).toEqual([['西']])
  expect(reopened.readonlyReason).toBeUndefined()
  expect(Object.values(output.cells).some(cell => cell.value === 40)).toBe(true)
  const zip = await createBufferEntrySource(saved)
  expect(await zip.readText(reopened.tablePath)).toContain('h="1"')
  expect((await zip.paths()).some(path => /slicer|timeline/i.test(path))).toBe(false)
  const next = pivotMemberFilterConfig(reopened, await readPivotFilterFields(saved, reopened), '地区', ['东', '西', '北'])
  const reset = await applyWorkbookOperations(saved, (await editPivotPlan(saved, reopened.tablePath, next)).operations)
  expect((await readWorkbookPivots(reset))[0]!.hiddenMembers?.row?.[0] ?? []).toEqual([])
})

it('uses an inclusive strict date interval and preserves selections on other dimensions', async () => {
  const { bytes, pivot } = await fixture(), fields = await readPivotFilterFields(bytes, pivot)
  const selected = pivotMemberFilterConfig(pivot, fields, '地区', ['东'])
  const config = pivotTimelineFilterConfig(selected, fields, '日期', '2024-01-02', '2024-01-03')
  expect(config.hiddenMembers).toEqual({ row: [['西', '北']], column: [['2024-01-01']] })
  expect(() => pivotTimelineFilterConfig(pivot, fields, '日期', '2024-02-30', '2024-03-01')).toThrow('有效日期')
  expect(() => pivotTimelineFilterConfig(pivot, fields, '日期', '2024-01-03', '2024-01-01')).toThrow('开始日期')
  expect(() => pivotTimelineFilterConfig(pivot, fields, '日期', '2025-01-01', '2025-01-03')).toThrow('没有匹配')
  expect(() => pivotMemberFilterConfig(pivot, fields, '地区', [])).toThrow('至少选择')
  expect(() => pivotMemberFilterConfig(pivot, fields, '地区', ['伪造成员'])).toThrow('成员已变化')
  const dateConfig = pivotTimelineFilterConfig(pivot, fields, '日期', '2024-01-02', '2024-01-03')
  const saved = await applyWorkbookOperations(bytes, (await editPivotPlan(bytes, pivot.tablePath, dateConfig)).operations)
  expect((await readWorkbookPivots(saved))[0]!.hiddenMembers?.column).toEqual([['2024-01-01']])
  expect(Object.values((await readWorkbook(saved)).sheets[0]!.cells).some(cell => cell.value === 50)).toBe(true)
})

it('recognizes formatted Excel dates with the 1904 epoch and leaves ordinary numbers ineligible', async () => {
  const { bytes, pivot } = await fixture(true), fields = await readPivotFilterFields(bytes, pivot)
  expect(fields.find(field => field.name === '日期')!.members[0]!.date).toBe('2024-01-01')
  const zip = await createBufferEntrySource(bytes), workbookXml = await zip.readText('xl/workbook.xml')
  const epoch1904 = (await assemblePackage(bytes, { replaced: new Map([['xl/workbook.xml', workbookXml.replace(/<workbookPr\b[^>]*(?:\/>|>\s*<\/workbookPr>)/, '').replace('<sheets>', '<workbookPr date1904="1"/><sheets>')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: ['xl/workbook.xml'] })).buffer
  expect((await readPivotFilterFields(epoch1904, pivot)).find(field => field.name === '日期')!.members[0]!.date).toBe('2028-01-02')
  const ordinary = await applyCellEdits(bytes, [1, 2, 3].map(row => ({ sheetName: 'Sheet1', row, column: 1, writeValue: false, cell: { value: null }, style: { numberFormat: '0' } })))
  expect((await readPivotFilterFields(ordinary, pivot)).find(field => field.name === '日期')!.timeline).toBe(false)
})

it('does not normalize invalid ISO dates or Excel phantom leap days into a timeline', async () => {
  const { bytes, pivot } = await fixture(true)
  const early = await applyCellEdits(bytes, [59, 60, 61].map((value, index) => ({ sheetName: 'Sheet1', row: index + 1, column: 1, writeValue: true, cell: { value } })))
  const field = (await readPivotFilterFields(early, pivot)).find(field => field.name === '日期')!
  expect(field.members.map(member => member.date)).toEqual(['1900-02-28', undefined, '1900-03-01'])
  expect(field.timeline).toBe(false)
  const invalid = await applyCellEdits(bytes, [{ sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: '2024-02-30' } }])
  expect((await readPivotFilterFields(invalid, pivot)).find(field => field.name === '日期')!.timeline).toBe(false)
})

it('refuses to desynchronize existing native slicer or timeline control state', async () => {
  const { bytes, pivot } = await fixture()
  for (const folder of ['slicerCaches', 'timelineCaches']) {
    const path = `xl/${folder}/cache1.xml`
    const native = (await assemblePackage(bytes, { replaced: new Map(), added: new Map([[path, '<nativeControl/>']]), addedBinary: new Map(), removedEntries: [], addedEntries: [path], touchedEntries: [] })).buffer
    await expect(readPivotFilterFields(native, pivot)).rejects.toThrow('无法同步')
  }
})
