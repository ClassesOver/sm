import type { ChartReadDesign } from '@sheets-web/xlsx-engine'

/** 固定源 f8c17004：ribbon-actions.ts 的 Quick Layout / Change Colors。
 * isPie 同时用于 pie 与 doughnut；canLabel 必须来自当前引擎的图类能力。
 * 本模块只返回改动字段，调用方保留图表身份并沿现有 applyChartEdits 链路登记。
 */
export interface ChartPresetSource {
  isPie: boolean
  canLabel: boolean
  seriesCount: number
  categoryCount: number
  hasAxes?: boolean
  canGroup?: boolean
  design?: ChartReadDesign | undefined
}

export interface ChartPresetEdit {
  grouping?: ChartGrouping
  legend?: 'right' | 'top' | 'bottom' | 'left' | 'none'
  dataLabels?: 'value' | 'percent' | 'category-percent' | 'none'
  seriesColors?: Record<string, string>
  pointColors?: Record<string, Record<string, string>>
}

const palettes = {
  office: ['#4472c4', '#ed7d31', '#a5a5a5', '#ffc000', '#5b9bd5', '#70ad47', '#264478', '#9e480e', '#636363', '#997300'],
  blue: ['#1f4e79', '#2e75b6', '#5b9bd5', '#9dc3e6', '#bdd7ee', '#2f5597'],
  green: ['#375623', '#548235', '#70ad47', '#a9d18e', '#c5e0b4', '#7fab55'],
  warm: ['#c00000', '#ed7d31', '#ffc000', '#bf8f00', '#843c0c', '#f4b183'],
  gray: ['#404040', '#7f7f7f', '#a6a6a6', '#bfbfbf', '#d0cece', '#595959'],
} as const

const layouts = [
  { id: '1', legend: 'right', label: '图例居右' },
  { id: '2', legend: 'top', label: '图例在上' },
  { id: '3', legend: 'bottom', label: '图例在下' },
  { id: '4', legend: 'none', label: '无图例' },
] as const
const colorLabels = { office: 'Office', blue: '单色蓝', green: '单色绿', warm: '暖色', gray: '灰度' }

const groupingModes = [
  { mode: 'clustered', label: '簇状（并列）' },
  { mode: 'stacked', label: '堆积' },
  { mode: 'percentStacked', label: '百分比堆积' },
] as const

export type ChartGrouping = typeof groupingModes[number]['mode']

const legendElements = [
  { mode: 'right', label: '图例：右' },
  { mode: 'top', label: '图例：上' },
  { mode: 'bottom', label: '图例：下' },
  { mode: 'left', label: '图例：左' },
  { mode: 'none', label: '图例：无' },
] as const

const labelElements = [
  { mode: 'category-percent', label: '数据标签：名称 + %' },
  { mode: 'percent', label: '数据标签：%' },
  { mode: 'value', label: '数据标签：数值' },
  { mode: 'none', label: '数据标签：无' },
] as const

export type ChartElementCommand =
  | `chart-legend:${typeof legendElements[number]['mode']}`
  | `chart-labels:${typeof labelElements[number]['mode']}`

function chartLabelElements(source: ChartPresetSource) {
  return source.canLabel ? labelElements.filter(({ mode }) => mode === 'none' || (mode === 'value' ? !source.isPie : source.isPie)) : []
}

export function chartPresetEdit(command: string, source: ChartPresetSource): ChartPresetEdit | null {
  const grouping = groupingModes.find(({ mode }) => command === `chart-grouping:${mode}`)
  if (grouping) return source.canGroup ? { grouping: grouping.mode } : null
  const legend = legendElements.find(({ mode }) => command === `chart-legend:${mode}`)
  if (legend) return { legend: legend.mode }
  const labels = chartLabelElements(source).find(({ mode }) => command === `chart-labels:${mode}`)
  if (labels && !(labels.mode === 'none' && source.design?.dataLabelsOffUnavailable)) return { dataLabels: labels.mode }
  const layout = layouts.find(item => command === `chart-layout:${item.id}`)
  if (layout) {
    return {
      legend: layout.legend,
      ...(source.canLabel ? { dataLabels: layout.id === '3' ? 'none' as const : source.isPie ? 'category-percent' as const : 'value' as const } : {}),
    }
  }
  const id = (Object.keys(palettes) as (keyof typeof palettes)[]).find(id => command === `chart-colors:${id}`)
  if (id) {
    const count = Math.min(source.isPie ? source.categoryCount : source.seriesCount, source.isPie ? 64 : 24)
    if (!(count > 0)) return null
    const palette = palettes[id]
    const colors = Object.fromEntries(Array.from({ length: count }, (_, index) => [String(index), palette[index % palette.length]!]))
    return source.isPie ? { pointColors: { '0': colors } } : { seriesColors: colors }
  }
  return null
}

export function chartPresetMenuOptions(kind: 'elements' | 'layout' | 'colors' | 'grouping', source: ChartPresetSource | null, editable = true): { command: string; label: string; disabled: boolean }[] {
  if (kind === 'grouping') {
    if (!source?.canGroup) return []
    const current = source.design?.grouping ?? 'clustered'
    return groupingModes.map(({ mode, label }) => ({
      command: `chart-grouping:${mode}`,
      label: label + (current === mode ? ' ✓' : ''),
      disabled: !editable,
    }))
  }
  if (kind === 'elements') {
    const disabled = !editable || !source
    const checked = (on: boolean) => on ? ' ✓' : ''
    return [
      { command: 'chart-title', label: '图表标题…', disabled },
      ...(source?.hasAxes ? [
        { command: 'chart-axis-cat', label: '轴标题：分类…' + checked(!!source.design?.axisTitles?.category), disabled },
        { command: 'chart-axis-val', label: '轴标题：数值…' + checked(!!source.design?.axisTitles?.value), disabled },
      ] : []),
      ...(source ? chartLabelElements(source).map(({ mode, label }) => ({
        command: `chart-labels:${mode}`, label: label + checked(source.design?.dataLabels === mode),
        disabled: disabled || (mode === 'none' && !!source.design?.dataLabelsOffUnavailable),
      })) : []),
      ...legendElements.map(({ mode, label }) => ({
        command: `chart-legend:${mode}`, label: label + checked(source?.design?.legend === mode), disabled,
      })),
    ]
  }
  if (kind === 'layout') {
    return layouts.map(layout => ({
      command: `chart-layout:${layout.id}`,
      label: `布局 ${layout.id} — ${layout.label}${!source?.canLabel ? '' : layout.id === '3' ? '，无标签' : source.isPie ? '，名称 + % 标签' : '，数值标签'}`,
      disabled: !editable || !source,
    }))
  }
  const disabled = !editable || !source || (source.isPie ? source.categoryCount : source.seriesCount) <= 0
  return (Object.keys(palettes) as (keyof typeof palettes)[]).map(id => ({
    command: `chart-colors:${id}`, label: colorLabels[id], disabled,
  }))
}
