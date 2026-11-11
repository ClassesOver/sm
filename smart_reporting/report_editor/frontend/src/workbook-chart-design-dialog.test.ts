import { afterEach, expect, it, vi } from 'vitest'
import { createChartDesignDialog } from './workbook-chart-design-dialog'

afterEach(() => document.body.replaceChildren())

it('prefills the chart title and submits the user text instead of a fixed title', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title', initialTitle: '原始标题' })
  const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
  expect(input.value).toBe('原始标题')
  input.value = '季度销售 & 订单'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart1.xml', title: '季度销售 & 订单' }, expect.objectContaining({ property: 'title' }))
  dialog.dispose()
})

it.each(['none', 'left', 'right', 'top', 'bottom'])('submits legend position %s', legend => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'legend' })
  document.querySelector<HTMLSelectElement>('[aria-label="图例位置"]')!.value = legend
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart1.xml', legend }, expect.objectContaining({ property: 'legend' }))
  dialog.dispose()
})

it('requires a legend choice and rejects an oversized title without applying', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  const target = { chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1' }
  dialog.open({ ...target, property: 'legend' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('请选择图例位置')
  dialog.open({ ...target, property: 'title' })
  document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!.value = '长'.repeat(201)
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('200')
  dialog.dispose()
})

it('submits the selected axis title and preserves the captured chart identity', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart4.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'categoryTitle' })
  const input = document.querySelector<HTMLInputElement>('[aria-label="分类轴标题"]')!
  input.value = '月份'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart4.xml', axisTitles: { category: '月份' } }, expect.objectContaining({ property: 'categoryTitle' }))
  dialog.dispose()
})

it('clears a blank axis title and allows choosing no data labels', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart2.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'valueTitle' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenLastCalledWith({ chartPath: 'xl/charts/chart2.xml', axisTitles: { value: null } }, expect.objectContaining({ property: 'valueTitle' }))
  dialog.open({ chartPath: 'xl/charts/chart2.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'labels' })
  document.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!.value = 'none'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenLastCalledWith({ chartPath: 'xl/charts/chart2.xml', dataLabels: 'none' }, expect.objectContaining({ property: 'labels' }))
  dialog.dispose()
})

it('cancels without applying a chart edit', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'categoryTitle' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-cancel]')!.click()
  expect(apply).not.toHaveBeenCalled()
  dialog.dispose()
})

it('submits grouped chart format and gridline settings', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart3.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'format' })
  document.querySelector<HTMLSelectElement>('[aria-label="图表分组"]')!.value = 'stacked'
  document.querySelector<HTMLInputElement>('[aria-label="显示主网格线"]')!.checked = true
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart3.xml', grouping: 'stacked', gridlines: true }, expect.objectContaining({ property: 'format' }))
  dialog.dispose()
})
