import { afterEach, expect, it, vi } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyChartAdditions } from '@sheets-web/xlsx-engine/chart-add'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { assemblePackage, createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'
import { createChartDesignDialog, type ChartDesignTarget } from './workbook-chart-design-dialog'

afterEach(() => document.body.replaceChildren())
const target = { chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1' }
const initial = { axisTitles: { category: '季度 & 月份', value: '营收（万元）' }, legend: 'bottom' as const,
  dataLabels: 'value' as const, grouping: 'stacked' as const, gridlines: true }

it.each([
  ['categoryTitle', '分类轴标题', '季度 & 月份'], ['valueTitle', '数值轴标题', '营收（万元）'],
  ['legend', '图例位置', 'bottom'], ['labels', '数据标签', 'value'], ['format', '图表分组', 'stacked'],
] as const)('prefills the actual %s and closes an unchanged confirmation without an edit', (property, label, value) => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ ...target, property, initial } as ChartDesignTarget)
  expect(document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!.value).toBe(value)
  if (property === 'format') expect(document.querySelector<HTMLInputElement>('[aria-label="显示主网格线"]')!.checked).toBe(true)
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true)
  dialog.dispose()
})

it('changes only the selected format field and preserves the other current setting', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ ...target, property: 'format', initial } as ChartDesignTarget)
  document.querySelector<HTMLInputElement>('[aria-label="显示主网格线"]')!.checked = false
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: target.chartPath, gridlines: false }, expect.objectContaining({ property: 'format' }))
  dialog.dispose()
})

it('does not rewrite a linked or long source title when it is unchanged', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ ...target, property: 'title', initialTitle: '原'.repeat(201), initial })
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true)
  dialog.dispose()
})

it('changes a prefilled axis title only when its text changes', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ ...target, property: 'categoryTitle', initial })
  document.querySelector<HTMLInputElement>('[aria-label="分类轴标题"]')!.value = ''
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: target.chartPath, axisTitles: { category: null } }, expect.anything())
  dialog.dispose()
})

it('keeps an unrepresented current setting until the user explicitly chooses a replacement', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ ...target, property: 'labels', initial: {} } as ChartDesignTarget)
  const select = document.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!
  expect(select.value).toBe('')
  expect(select.selectedOptions[0]!.textContent).toContain('保留')
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  dialog.open({ ...target, property: 'labels', initial: {} } as ChartDesignTarget)
  select.value = 'none'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: target.chartPath, dataLabels: 'none' }, expect.anything())
  dialog.dispose()
})

it('reopens another chart with its own state and cancels without applying', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ ...target, property: 'format', initial } as ChartDesignTarget)
  document.querySelector<HTMLSelectElement>('[aria-label="图表分组"]')!.value = 'clustered'
  document.querySelector<HTMLButtonElement>('[data-chart-design-cancel]')!.click()
  dialog.open({ ...target, chartPath: 'xl/charts/chart2.xml', property: 'format', initial: { grouping: 'percentStacked', gridlines: false } } as ChartDesignTarget)
  expect(document.querySelector<HTMLSelectElement>('[aria-label="图表分组"]')!.value).toBe('percentStacked')
  expect(document.querySelector<HTMLInputElement>('[aria-label="显示主网格线"]')!.checked).toBe(false)
  document.querySelector<HTMLButtonElement>('[data-chart-design-cancel]')!.click()
  expect(apply).not.toHaveBeenCalled()
  dialog.dispose()
})

it.each(['column', 'line', 'area'] as const)('reads actual %s design settings from the XLSX without changing the source', async chartType => {
  let bytes = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 12, toColumn: 12, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType, title: '来源标题', series: [{ name: '收入', valuesRef: 'Sheet1!B2:B3', values: [3, 7], categories: ['甲', '乙'] }] },
  }])
  bytes = await applyWorkbookOperations(bytes, [{ kind: 'applyChartEdits', edits: [{ chartPath: target.chartPath, ...initial }] }])
  const before = bytes.slice(), chart = (await readWorkbook(bytes)).sheets[0]!.charts![0]!
  expect(chart).toMatchObject({ design: initial })
  expect(bytes).toEqual(before)
})

it.each(['series', 'point', 'unsupported'] as const)('keeps %s-specific labels as custom instead of showing a false default', async mode => {
  let bytes = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 12, toColumn: 12, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: '', series: [{ name: '收入', valuesRef: 'Sheet1!B2:B3', values: [3, 7], categories: ['甲', '乙'] }] },
  }])
  const source = await createBufferEntrySource(bytes), original = await source.readText(target.chartPath)
  const xml = mode === 'series' ? original.replace('</c:ser>', '<c:dLbls><c:showVal val="1"/></c:dLbls></c:ser>')
    : original.replace('</c:barChart>', `<c:dLbls>${mode === 'point' ? '<c:dLbl><c:idx val="0"/><c:showVal val="1"/></c:dLbl>' : '<c:showSerName val="1"/>'}</c:dLbls></c:barChart>`)
  bytes = (await assemblePackage(bytes, { replaced: new Map([[target.chartPath, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [target.chartPath] })).buffer
  const chart = (await readWorkbook(bytes)).sheets[0]!.charts![0]!
  expect(chart).toMatchObject({ design: { axisTitles: { category: '', value: '' }, gridlines: false } })
  expect((chart as typeof chart & { design: typeof initial }).design.dataLabels).toBeUndefined()
})
