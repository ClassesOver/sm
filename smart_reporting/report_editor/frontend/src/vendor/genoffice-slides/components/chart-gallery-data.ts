/**
 * Adapted from GenOffice apps/slides/src/renderer/insert-presets.ts (CHART_GALLERY, chartSampleData)
 * at f8c17004fb730df11f0f743164ffd8b4281bb38c, with the Simplified Chinese strings from
 * packages/i18n/src/common-ribbon.ts / apps/slides/src/renderer/i18n/ribbon/zh.ts substituted for
 * the i18n keys. Gallery order, kinds and sample values are unchanged.
 */
export type ChartGalleryKind = 'bar' | 'bar3D' | 'barStacked' | 'barPercentStacked' | 'barH' | 'line' | 'area' | 'pie' | 'pie3D' | 'doughnut' | 'scatter' | 'radar' | 'comboBarLine'
export const CHART_GALLERY: { kind: ChartGalleryKind; label: string }[] = [
  { kind: 'bar', label: '簇状柱形图' },
  { kind: 'barStacked', label: '堆积柱形图' },
  { kind: 'barPercentStacked', label: '百分比堆积柱形' },
  { kind: 'barH', label: '条形图' },
  { kind: 'bar3D', label: '三维簇状柱形图' },
  { kind: 'line', label: '折线图' },
  { kind: 'area', label: '面积图' },
  { kind: 'pie', label: '饼图' },
  { kind: 'pie3D', label: '三维饼图' },
  { kind: 'doughnut', label: '环形图' },
  { kind: 'scatter', label: '散点图' },
  { kind: 'radar', label: '雷达图' },
  { kind: 'comboBarLine', label: '组合图(柱线)' },
]
export function chartSampleData(kind: ChartGalleryKind): { categories: string[]; series: { name: string; values: number[] }[] } {
  const quarters = ['第一季度', '第二季度', '第三季度', '第四季度']
  if (kind === 'pie' || kind === 'pie3D' || kind === 'doughnut') return { categories: quarters, series: [{ name: '销售额', values: [8.2, 3.2, 1.4, 1.2] }] }
  // Categories are the X values (numeric strings; the engine writes c:xVal)
  if (kind === 'scatter') return { categories: ['0.7', '1.8', '2.6', '3.2', '4.5', '5.1'], series: [{ name: 'Y 值', values: [2.7, 3.2, 0.8, 1.2, 1.9, 2.5] }] }
  if (kind === 'comboBarLine') return { categories: quarters, series: [{ name: '销售额', values: [4.3, 2.5, 3.5, 4.5] }, { name: '成本', values: [2.4, 1.8, 2.6, 2.8] }, { name: '增长率', values: [2.0, 1.2, 2.6, 3.4] }] }
  if (kind === 'radar') return { categories: ['沟通', '协作', '执行', '创新', '领导'], series: [{ name: '系列 1', values: [3.5, 4.2, 3.0, 4.5, 3.8] }, { name: '系列 2', values: [4.4, 2.5, 4.0, 2.8, 3.2] }] }
  return { categories: [1, 2, 3, 4].map(n => `类别 ${n}`), series: [{ name: '系列 1', values: [4.3, 2.5, 3.5, 4.5] }, { name: '系列 2', values: [2.4, 4.4, 1.8, 2.8] }, { name: '系列 3', values: [2, 2, 3, 5] }] }
}
