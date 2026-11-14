import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook, createBufferEntrySource, inventoryXlsx } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'

const source = (operation: Record<string, unknown>) => ({ kind: 'applyChartSource', operation })
const add = (extra = {}) => source({ op: 'add_chart', sheetId: "O'Brien", chartType: 'line', dataRange: 'A1:B4', title: '收入（万元）', ...extra })
async function workbook() {
  return applyWorkbookOperations(await createBlankWorkbook("O'Brien"), [{ kind: 'applyCellEdits', edits:
    [['期间', '收入'], ['Q1', 10], ['Q2', 20], ['Q3', 30]].flatMap((values, row) => values.map((value, column) => ({ sheetName: "O'Brien", row, column, writeValue: true, cell: { value } }))) }])
}
const xml = async (bytes: Uint8Array, path = 'xl/charts/chart1.xml') => (await createBufferEntrySource(bytes)).readText(path)

it.each(['column', 'bar', 'line', 'area', 'pie', 'doughnut', 'scatter', 'radar', 'combo'])('源范围创建 %s，写真实缓存、转义引用和明确锚点', async chartType => {
  const after = await applyWorkbookOperations(await workbook(), [add({ chartType, anchorCell: 'G5' })])
  const chart = (await readWorkbook(after)).sheets[0]!.charts![0]!
  expect(chart.anchor.fromRow).toBe(4); expect(chart.anchor.fromColumn).toBe(6)
  expect(await xml(after)).toContain('10'); expect(await xml(after)).toContain('30')
  expect(await xml(after)).toContain("'O''Brien'!$B$2:$B$4")
})

it('从本批当前值创建、换绑时同步新引用与缓存，仅改目标图表', async () => {
  const before = await applyWorkbookOperations(await workbook(), [add(), add({ anchorCell: 'N1' })])
  const cell = { kind: 'applyCellEdits', edits: [{ sheetName: "O'Brien", row: 2, column: 1, writeValue: true, cell: { value: 73 } }] }
  const after = await applyWorkbookOperations(before, [cell, source({ op: 'edit_chart', chartPath: 'xl/charts/chart1.xml', seriesData: [{ index: 0, name: '修订收入', valuesRange: 'B3:B4', categoriesRange: 'A3:A4' }] })])
  const chartXml = await xml(after)
  expect(chartXml).toContain('修订收入'); expect(chartXml).toContain('$B$3:$B$4'); expect(chartXml).toContain('73')
  expect(chartXml).toContain('Q2'); expect(chartXml).not.toContain('Q1')
  expect(await xml(after, 'xl/charts/chart2.xml')).toBe(await xml(before, 'xl/charts/chart2.xml'))
  const inventory = await inventoryXlsx(before)
  expect((await inventoryXlsx(after)).filter(item => inventory.find(old => old.path === item.path)?.sha256 !== item.sha256).map(item => item.path).sort()).toEqual(['xl/charts/chart1.xml', 'xl/worksheets/sheet1.xml'])
})

it.each([
  { dataRange: 'A1:XFE2' }, { dataRange: 'A1:B1001' }, { dataRange: 'B4:A1' },
  { dataRange: 'A1:A4' }, { sheetId: '不存在' }, { anchorCell: 'XFD1048576' },
  { series: [{ values: [999] }] },
])('源范围或不可信缓存拒绝 %j', async extra => {
  await expect(applyWorkbookOperations(await workbook(), [add(extra)])).rejects.toThrow()
})

it.each([
  [{ index: 3, name: '不存在' }], [{ index: 0, valuesRange: 'A1:B4' }],
  [{ index: 0, valuesRange: 'B2:B4', categoriesRange: 'A2:A3' }],
  [{ index: 0, values: [999] }], [{ index: 0, sheetId: '不存在', valuesRange: 'B2:B4' }],
  [{ index: 0, name: '一次' }, { index: 0, name: '重复' }],
].map(seriesData => ({ seriesData })))('换绑拒绝无效完整提案 $seriesData', async ({ seriesData }) => {
  const before = await applyWorkbookOperations(await workbook(), [add()])
  await expect(applyWorkbookOperations(before, [source({ op: 'edit_chart', chartPath: 'xl/charts/chart1.xml', seriesData })])).rejects.toThrow()
})

it('源默认单系列标题与柱形数值标签，多系列饼图仅取第一数值系列', async () => {
  const base = await workbook()
  const column = await applyWorkbookOperations(base, [add({ chartType: 'column', title: undefined })])
  expect((await readWorkbook(column)).sheets[0]!.charts![0]!.title).toBe('收入')
  expect(await xml(column)).toContain('<c:showVal val="1"')
  const extra = { kind: 'applyCellEdits', edits: [{ sheetName: "O'Brien", row: 0, column: 2, writeValue: true, cell: { value: '成本' } }, ...[1, 2, 3].map(row => ({ sheetName: "O'Brien", row, column: 2, writeValue: true, cell: { value: row*2 } }))] }
  const pie = await applyWorkbookOperations(base, [extra, add({ chartType: 'pie', dataRange: 'A1:C4' })])
  expect((await readWorkbook(pie)).sheets[0]!.charts![0]!.series).toHaveLength(1)
  const doughnut = await applyWorkbookOperations(base, [extra, add({ chartType: 'doughnut', dataRange: 'A1:C4' })])
  expect((await readWorkbook(doughnut)).sheets[0]!.charts![0]!.series).toHaveLength(2)
})

it('纯数值源使用序号分类，不写指向数值列的伪分类引用', async () => {
  const output = await applyWorkbookOperations(await workbook(), [add({ dataRange: 'B2:B4' })])
  const chart = (await readWorkbook(output)).sheets[0]!.charts![0]!
  expect(chart.series[0]!.valuesRef).toBe("'O''Brien'!$B$2:$B$4")
  expect(chart.series[0]!.categoriesRef).toBeUndefined()
  expect(chart.series[0]!.categories).toEqual(['1', '2', '3'])
})
