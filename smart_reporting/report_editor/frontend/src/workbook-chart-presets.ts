/** 固定源 f8c17004：ribbon-actions.ts 的 Quick Layout / Change Colors。
 * isPie 同时用于 pie 与 doughnut；canLabel 必须来自当前引擎的图类能力。
 * 本模块只返回改动字段，调用方保留图表身份并沿现有 applyChartEdits 链路登记。
 */
export interface ChartPresetSource {
  isPie: boolean
  canLabel: boolean
  seriesCount: number
  categoryCount: number
}

export interface ChartPresetEdit {
  legend?: 'right' | 'top' | 'bottom' | 'none'
  dataLabels?: 'value' | 'category-percent' | 'none'
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

export function chartPresetEdit(command: string, source: ChartPresetSource): ChartPresetEdit | null {
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

export function chartPresetMenuOptions(kind: 'layout' | 'colors', source: ChartPresetSource | null, editable = true): { command: string; label: string; disabled: boolean }[] {
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
