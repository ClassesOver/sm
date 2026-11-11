/** GenOffice f8c17004 Ribbon CHART_STYLE_PRESETS / main chartColorSchemes 的纯数据适配。 */
export const CHART_SCHEME_KEYS = ['default', 'colorful', 'colorful2', 'mono-accent1', 'mono-accent2', 'mono-accent3', 'mono-accent4', 'mono-accent5', 'mono-accent6', 'blue', 'warm', 'cool', 'mono'] as const
export type ChartSchemeKey = typeof CHART_SCHEME_KEYS[number]
export type ChartColorScheme = { key: ChartSchemeKey; label: string; colors: string[] }
export type ChartDesignPatch = { colorScheme?: ChartSchemeKey; gapWidthPct?: number }
export const CHART_STYLE_PRESETS = [
  { key: 'classic', label: '经典', style: { legendPos: 'b', dataLabels: false, gridlines: false, gapWidthPct: 150 } },
  { key: 'grid', label: '网格', style: { legendPos: 'b', dataLabels: false, gridlines: true, gapWidthPct: 150 } },
  { key: 'labeled', label: '数据标签', style: { legendPos: 'b', dataLabels: true, gridlines: false, gapWidthPct: 150 } },
  { key: 'detail', label: '标签+网格', style: { legendPos: 'b', dataLabels: true, gridlines: true, gapWidthPct: 150 } },
  { key: 'minimal', label: '极简', style: { legendPos: 'none', dataLabels: false, gridlines: false, gapWidthPct: 150 } },
  { key: 'minimal-labeled', label: '极简标签', style: { legendPos: 'none', dataLabels: true, gridlines: false, gapWidthPct: 150 } },
  { key: 'bold', label: '粗柱', style: { legendPos: 'b', dataLabels: false, gridlines: true, gapWidthPct: 50 } },
  { key: 'slim', label: '细柱', style: { legendPos: 'b', dataLabels: false, gridlines: true, gapWidthPct: 300 } },
  { key: 'legend-top', label: '顶部图例', style: { legendPos: 't', dataLabels: false, gridlines: true, gapWidthPct: 150 } },
  { key: 'legend-right', label: '右侧图例', style: { legendPos: 'r', dataLabels: false, gridlines: true, gapWidthPct: 150 } },
] as const

export function validChartDesign(value: Record<string, unknown>): boolean {
  return (!Object.hasOwn(value, 'colorScheme') || CHART_SCHEME_KEYS.includes(value.colorScheme as ChartSchemeKey))
    && (!Object.hasOwn(value, 'gapWidthPct') || typeof value.gapWidthPct === 'number' && Number.isInteger(value.gapWidthPct) && value.gapWidthPct >= 0 && value.gapWidthPct <= 500)
}

const FALLBACK_ACCENTS = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
function mixHex(hex: string, target: number, ratio: number): string {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex)
  if (!m) return hex
  const v = parseInt(m[1]!, 16), ch = (x: number) => Math.round(x + (target - x) * ratio)
  return `#${((ch((v >> 16) & 255) << 16) | (ch((v >> 8) & 255) << 8) | ch(v & 255)).toString(16).padStart(6, '0').toUpperCase()}`
}
export function chartColorSchemes(accents: string[] = FALLBACK_ACCENTS): ChartColorScheme[] {
  const acc = accents.length >= 3 ? accents : FALLBACK_ACCENTS
  return [
    { key: 'default', label: '主题默认', colors: [] },
    { key: 'colorful', label: '彩色', colors: [...acc] },
    { key: 'colorful2', label: '彩色 2', colors: [...acc.slice(3), ...acc.slice(0, 3)] },
    ...acc.map((color, index): ChartColorScheme => ({ key: `mono-accent${index + 1}` as ChartSchemeKey, label: `单色 ${index + 1}`, colors: [mixHex(color, 0, .25), color, mixHex(color, 255, .25), mixHex(color, 255, .45), mixHex(color, 255, .65)] })),
    { key: 'blue', label: '蓝调', colors: ['#2E75B6', '#4472C4', '#5B9BD5', '#70AD47', '#ED7D31'] },
    { key: 'warm', label: '暖色', colors: ['#ED7D31', '#FFC000', '#FF0000', '#C55A11', '#833C00'] },
    { key: 'cool', label: '冷色', colors: ['#0070C0', '#00B0F0', '#00B0A0', '#7030A0', '#2E75B6'] },
    { key: 'mono', label: '单色', colors: ['#404040', '#666666', '#888888', '#AAAAAA', '#CCCCCC'] },
  ]
}
