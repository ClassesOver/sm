import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { chartAdditionFromGrid } from './workbook-chart-add'
import { chartPresetEdit, chartPresetMenuOptions, type ChartPresetSource } from './workbook-chart-presets'

const axis: ChartPresetSource = { isPie: false, canLabel: true, seriesCount: 2, categoryCount: 3 }

it.each([
  ['1', 'right', 'value'], ['2', 'top', 'value'], ['3', 'bottom', 'none'], ['4', 'none', 'value'],
])('applies quick layout %s to axis charts', (id, legend, dataLabels) => {
  expect(chartPresetEdit(`chart-layout:${id}`, axis)).toEqual({ legend, dataLabels })
})

it.each(['1', '2', '4'])('uses category and percent labels for pie/doughnut layout %s', id => {
  expect(chartPresetEdit(`chart-layout:${id}`, { ...axis, isPie: true })).toMatchObject({ dataLabels: 'category-percent' })
})

it.each(['1', '2', '3', '4'])('only edits the legend for label-less chart layout %s', id => {
  const patch = chartPresetEdit(`chart-layout:${id}`, { ...axis, canLabel: false })!
  expect(Object.keys(patch)).toEqual(['legend'])
})

it.each([
  ['office', '#4472c4', '#ed7d31'], ['blue', '#1f4e79', '#2e75b6'],
  ['green', '#375623', '#548235'], ['warm', '#c00000', '#ed7d31'], ['gray', '#404040', '#7f7f7f'],
])('applies %s palette to real series indices', (id, first, second) => {
  expect(chartPresetEdit(`chart-colors:${id}`, axis)).toEqual({ seriesColors: { '0': first, '1': second } })
})

it('cycles source palette colors up to the 24-series save limit', () => {
  const patch = chartPresetEdit('chart-colors:blue', { ...axis, seriesCount: 30 })!
  expect(Object.keys(patch.seriesColors!)).toHaveLength(24)
  expect(patch.seriesColors).toMatchObject({ '5': '#2f5597', '6': '#1f4e79', '23': '#2f5597' })
  expect(patch.seriesColors!['24']).toBeUndefined()
})

it('recolors pie points on series zero, cycles and caps at 64 points', () => {
  const patch = chartPresetEdit('chart-colors:office', { ...axis, isPie: true, categoryCount: 70 })!
  expect(patch.seriesColors).toBeUndefined()
  expect(Object.keys(patch.pointColors!)).toEqual(['0'])
  expect(Object.keys(patch.pointColors!['0']!)).toHaveLength(64)
  expect(patch.pointColors!['0']).toMatchObject({ '9': '#997300', '10': '#4472c4', '63': '#ffc000' })
})

it('does not emit empty recolors or accept unknown commands', () => {
  expect(chartPresetEdit('chart-colors:office', { ...axis, seriesCount: 0 })).toBeNull()
  expect(chartPresetEdit('chart-colors:office', { ...axis, isPie: true, categoryCount: 0 })).toBeNull()
  for (const command of ['chart-layout:5', 'chart-colors:unknown', 'chart-colors:toString', 'chart-title:x']) {
    expect(chartPresetEdit(command, axis)).toBeNull()
  }
})

it('offers executable Chinese options and accurately labels unsupported data labels', () => {
  const pieOptions = chartPresetMenuOptions('layout', { ...axis, isPie: true })
  expect(pieOptions.map(option => option.command)).toEqual(['chart-layout:1', 'chart-layout:2', 'chart-layout:3', 'chart-layout:4'])
  expect(pieOptions[0]!.label).toContain('名称 + % 标签')
  expect(chartPresetMenuOptions('layout', axis)[0]!.label).toContain('数值标签')
  const labelLess = chartPresetMenuOptions('layout', { ...axis, canLabel: false })
  expect(labelLess.every(option => !option.label.includes('标签'))).toBe(true)
  expect(chartPresetMenuOptions('colors', axis).map(option => option.command)).toEqual([
    'chart-colors:office', 'chart-colors:blue', 'chart-colors:green', 'chart-colors:warm', 'chart-colors:gray',
  ])
  for (const option of [...pieOptions, ...chartPresetMenuOptions('colors', axis)]) {
    expect(option.disabled).toBe(false)
    expect(chartPresetEdit(option.command, axis)).not.toBeNull()
  }
})

it('disables menus without an editable target and disables only colors for empty data', () => {
  expect(chartPresetMenuOptions('layout', null).every(option => option.disabled)).toBe(true)
  expect(chartPresetMenuOptions('colors', axis, false).every(option => option.disabled)).toBe(true)
  expect(chartPresetMenuOptions('colors', { ...axis, seriesCount: 0 }).every(option => option.disabled)).toBe(true)
  expect(chartPresetMenuOptions('layout', { ...axis, seriesCount: 0 }).every(option => !option.disabled)).toBe(true)
})

it.each(['column', 'pie', 'doughnut'] as const)('saves and independently reopens %s layout and palette edits', async chartType => {
  const addition = chartAdditionFromGrid({ sheetName: 'Sheet1', chartType, title: '季度收入',
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, values: [['季度', '收入'], ['Q1', 10], ['Q2', 20]] })
  let bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applyChartAdditions', additions: [addition] }])
  const before = (await readWorkbook(bytes)).sheets[0]!.charts![0]!
  const source = { ...axis, isPie: chartType !== 'column', seriesCount: 1, categoryCount: 2 }
  bytes = await applyWorkbookOperations(bytes, [{ kind: 'applyChartEdits', edits: [{
    chartPath: before.chartPath, ...chartPresetEdit('chart-layout:2', source), ...chartPresetEdit('chart-colors:warm', source),
  }] }])
  const chart = (await readWorkbook(bytes)).sheets[0]!.charts![0]!
  expect(chart).toMatchObject({ kind: chartType, title: '季度收入', legend: { position: 'top' } })
  const xml = await (await createBufferEntrySource(bytes)).readText(chart.chartPath)
  expect(xml).toContain(`<c:showVal val="${source.isPie ? '0' : '1'}"/>`)
  expect(xml).toContain(`<c:showCatName val="${source.isPie ? '1' : '0'}"/>`)
  expect(xml).toContain(`<c:showPercent val="${source.isPie ? '1' : '0'}"/>`)
  if (source.isPie) expect(chart.series[0]!.pointColors).toMatchObject({ 0: '#C00000', 1: '#ED7D31' })
  else expect(chart.series[0]!.color).toBe('#C00000')
})
