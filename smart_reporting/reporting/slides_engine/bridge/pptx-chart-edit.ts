/** 固定源 ChartDataDialog / ChartTypeDialog：仅重建框架自身创建的原生图表。 */
import { editChartElement, type OpenedPptx } from '@genoffice/pptx-engine'
import { resolveTarget } from '../packages/pptx-engine/src/zip.ts'
import { transposeChartData, transposeChartPointColors, validChartPointColors, type ChartPointColors } from './pptx-chart-data.ts'
import { validChartDesign, type ChartDesignPatch } from './pptx-chart-design.ts'
import { inspectChartColorSchemes } from './pptx-chart-schemes.ts'

export const NATIVE_CHART_KINDS = ['bar', 'barStacked', 'barPercentStacked', 'barH', 'bar3D', 'line', 'area', 'pie', 'pie3D', 'doughnut', 'scatter', 'radar', 'comboBarLine'] as const
export type NativeChartKind = typeof NATIVE_CHART_KINDS[number]
export type NativeChartStyle = { title: string; catAxisTitle: string; valAxisTitle: string; legendPos: 'b' | 't' | 'r' | 'l' | 'none'; dataLabels: boolean; gridlines: boolean }
export type NativeChartEdit = Partial<NativeChartStyle> & ChartDesignPatch & { slideIndex: number; elementId: string; kind?: NativeChartKind; switchRowCol?: boolean; categories?: string[]; series?: { name: string; values: number[] }[]; pointColors?: ChartPointColors }
const styleFields = ['title', 'catAxisTitle', 'valAxisTitle', 'legendPos', 'dataLabels', 'gridlines', 'colorScheme', 'gapWidthPct', 'pointColors']
const title = (value: unknown): value is string => typeof value === 'string' && [...value].length <= 1000 && !/[\u0000-\u001f\u007f\ud800-\udfff\ufffe\uffff]/u.test(value)
type Conflicts = { deletedSlides?: number[]; deletions?: { slideIndex: number; elementId: string }[] }
const reason = 'pptx_chart_source_unsupported'
const label = (value: unknown): value is string => typeof value === 'string' && [...value].length <= 100 && !/[\u0000-\u001f\u007f]/.test(value)

export function inspectChartEdit(opened: OpenedPptx, slideIndex: number, elementId: string) {
  const unavailable = { chartEditSafe: false, chartEditReason: reason, chartKind: null, chartCategories: null, chartSeries: null, chartStyle: null, chartGapWidthPct: null, chartColorSchemes: null, chartPointColors: null, chartSeriesColors: null }
  const slide = opened.deck.slides[slideIndex]
  const element = slide?.elements.find(el => el.id === elementId)
  if (!slide || element?.type !== 'chart' || element.descr !== 'aislides-chart') return unavailable
  const model = element.chart
  const rId = /r:id=["']([^"']+)["']/.exec(element.anchor.originalXml)?.[1]
  const rel = rId ? opened.archive.readRels(slide.path).get(rId) : undefined
  if (!rel || !rel.type.endsWith('/chart') || rel.targetMode === 'External') return unavailable
  const path = resolveTarget(slide.path, rel.target)
  // 一个 chart part 或嵌入工作簿被多个图形引用时，原位重建会误改其他图表。
  let references = 0
  for (const sourceSlide of opened.deck.slides) {
    const sourceRels = opened.archive.readRels(sourceSlide.path)
    for (const sourceElement of sourceSlide.elements) {
      if (sourceElement.type !== 'chart') continue
      const sourceId = /r:id=["']([^"']+)["']/.exec(sourceElement.anchor.originalXml)?.[1]
      const sourceRel = sourceId ? sourceRels.get(sourceId) : undefined
      if (sourceRel && resolveTarget(sourceSlide.path, sourceRel.target) === path) references++
    }
  }
  if (references !== 1) return unavailable
  const workbookPaths = [...opened.archive.readRels(path).values()].filter(item => item.type.endsWith('/package')).map(item => resolveTarget(path, item.target))
  if (workbookPaths.length !== 1 || !opened.archive.entries.has(workbookPaths[0]!)) return unavailable
  for (const part of opened.archive.entries.keys()) {
    if (!/^ppt\/charts\/_rels\/[^/]+\.rels$/.test(part)) continue
    const chartPath = part.replace('/_rels/', '/').replace(/\.rels$/, '')
    if (chartPath === path) continue
    if ([...opened.archive.readRels(chartPath).values()].some(item => item.type.endsWith('/package') && workbookPaths.includes(resolveTarget(chartPath, item.target)))) return unavailable
  }
  const xml = opened.archive.readText(path)
  // 重建器不保留扩展、外部数据连接、日期/多层类别、趋势线和特殊标签，不能静默丢弃。
  if (!xml || /<(?:\w+:)?(?:AlternateContent|multiLvlStrRef|dateAx|trendline|errBars|userShapes|pivotSource|numFmt)\b/.test(xml)
    || /<c:extLst\b/.test(xml)
    || /<c:cat>\s*<c:numRef\b/.test(xml)
    || [...opened.archive.readRels(path).values()].some(item => !item.type.endsWith('/package') || item.targetMode === 'External' || !item.target.endsWith('.xlsx'))
    || !['bar', 'line', 'area', 'pie', 'scatter', 'radar'].includes(model.kind)
    || !model.categories.length || model.categories.length > 100 || !model.categories.every(label)
    || !model.series.length || model.series.length > 20
    || model.series.some(series => !label(series.name ?? '') || series.values.length !== model.categories.length || series.values.some(value => typeof value !== 'number' || !Number.isFinite(value)))) return unavailable
  const combo = model.kind === 'bar' && model.series.some(series => series.plotKind === 'line')
  const kind: NativeChartKind = combo ? 'comboBarLine' : model.kind === 'bar'
    ? model.barDir === 'bar' ? 'barH' : model.grouping === 'percentStacked' ? 'barPercentStacked' : model.grouping === 'stacked' ? 'barStacked' : model.pseudo3D ? 'bar3D' : 'bar'
    : model.kind === 'pie' ? model.holePct ? 'doughnut' : model.pseudo3D ? 'pie3D' : 'pie' : model.kind as NativeChartKind
  const categories = kind === 'scatter' ? model.series[0]!.xValues?.map(value => String(value)) : model.categories
  if (!categories || (kind === 'scatter' && model.series.some(series => !series.xValues || series.xValues.length !== categories.length || series.xValues.some((value, index) => typeof value !== 'number' || !Number.isFinite(value) || value !== Number(categories[index]))))) return unavailable
  const chartStyle: NativeChartStyle = { title: model.title ?? '', catAxisTitle: model.catAxis?.title ?? '', valAxisTitle: model.valAxis?.title ?? '', legendPos: model.legendPos === 'tr' ? 'r' : model.legendPos ?? 'none', dataLabels: !!model.dataLabels, gridlines: !!model.valAxis?.gridColor }
  return { chartEditSafe: true, chartEditReason: null, chartKind: kind, chartCategories: [...categories], chartSeries: model.series.map(series => ({ name: series.name ?? '', values: [...series.values] as number[] })), chartStyle, chartGapWidthPct: model.gapWidthPct ?? 150, chartColorSchemes: inspectChartColorSchemes(opened), chartPointColors: model.series.map(series => categories.map((_, index) => series.pointColors?.[index] ?? null)), chartSeriesColors: model.series.map(series => series.color ?? null) }
}

export function validateChartEdits(opened: OpenedPptx, input: unknown, conflicts: Conflicts = {}): NativeChartEdit[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 50) throw new Error('pptx_chart_edits_invalid')
  const seen = new Set<string>()
  for (const item of input) {
    if (!item || typeof item !== 'object' || Object.keys(item).some(key => !['slideIndex', 'elementId', 'kind', 'switchRowCol', 'categories', 'series', ...styleFields].includes(key))
      || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= opened.deck.slides.length || typeof item.elementId !== 'string'
      || (item.kind === undefined && item.categories === undefined && !Object.hasOwn(item, 'switchRowCol') && !styleFields.some(key => Object.hasOwn(item, key))) || (item.categories === undefined) !== (item.series === undefined)
      || (Object.hasOwn(item, 'switchRowCol') && typeof item.switchRowCol !== 'boolean')
      || (item.kind !== undefined && !NATIVE_CHART_KINDS.includes(item.kind))) throw new Error('pptx_chart_edit_invalid')
    if (!validChartDesign(item) || ['title', 'catAxisTitle', 'valAxisTitle'].some(key => Object.hasOwn(item, key) && !title(item[key]))
      || (Object.hasOwn(item, 'legendPos') && !['b', 't', 'r', 'l', 'none'].includes(item.legendPos))
      || ['dataLabels', 'gridlines'].some(key => Object.hasOwn(item, key) && typeof item[key] !== 'boolean')) throw new Error('pptx_chart_style_invalid')
    const key = `${item.slideIndex}:${item.elementId}`
    if (seen.has(key) || conflicts.deletedSlides?.includes(item.slideIndex) || conflicts.deletions?.some(deletion => deletion.slideIndex === item.slideIndex && deletion.elementId === item.elementId)) throw new Error('pptx_chart_edit_target_conflict')
    seen.add(key)
    const state = inspectChartEdit(opened, item.slideIndex, item.elementId)
    if (!state.chartEditSafe) throw new Error(reason)
    if (item.colorScheme !== undefined && !state.chartColorSchemes!.some(scheme => scheme.key === item.colorScheme)) throw new Error('pptx_chart_palette_unavailable')
    const source = { categories: state.chartCategories!, series: state.chartSeries! }
    const { categories, series } = item.categories === undefined ? item.switchRowCol ? transposeChartData(source) : source : item
    if (!Array.isArray(categories) || categories.length < 1 || categories.length > 100 || !categories.every(label)
      || !Array.isArray(series) || series.length < 1 || series.length > 20
      || series.some(row => !row || Object.keys(row).sort().join() !== 'name,values' || !label(row.name) || !Array.isArray(row.values) || row.values.length !== categories.length || row.values.some((value: unknown) => typeof value !== 'number' || !Number.isFinite(value)))) throw new Error('pptx_chart_data_invalid')
    const kind = item.kind ?? state.chartKind
    if (Object.hasOwn(item, 'pointColors') && (kind === 'scatter' || !validChartPointColors(item.pointColors, series.length, categories.length))) throw new Error('pptx_chart_point_colors_invalid')
    if ((kind === 'comboBarLine' && series.length < 2) || (kind === 'scatter' && categories.some((value: string) => !value.trim() || !Number.isFinite(Number(value))))) throw new Error('pptx_chart_data_invalid')
  }
  return input as NativeChartEdit[]
}

/** 必须先整体 validate；同一目标的 data/type patch 由宿主合并，避免陈旧模型覆盖。 */
export function applyChartEdits(opened: OpenedPptx, edits: NativeChartEdit[]) {
  for (const { slideIndex, elementId, kind, switchRowCol, categories, series, colorScheme, pointColors, ...style } of edits) {
    const state = inspectChartEdit(opened, slideIndex, elementId)
    if (!state.chartEditSafe) throw new Error(reason)
    // 散点图解析器把 x 缓存存入 xValues；显式传回，避免 kind-only 修改丢失 x。
    // 显式数据为最终方向；反投影后交给原生 switchRowCol，同时由引擎转置单点颜色。
    const data = categories === undefined ? { categories: state.chartCategories!, series: state.chartSeries! }
      : switchRowCol ? transposeChartData({ categories, series: series! }) : { categories, series: series! }
    const palette = colorScheme === undefined ? undefined : state.chartColorSchemes!.find(scheme => scheme.key === colorScheme)!.colors
    const patch = { ...style, ...(pointColors ? { pointColors: switchRowCol ? transposeChartPointColors(pointColors) : pointColors } : {}), ...(palette === undefined ? {} : { colorScheme: palette }), switchRowCol, ...(kind ? { kind: kind === 'barH' ? 'bar' as const : kind, ...(kind === 'barH' ? { barDir: 'bar' as const } : {}) } : {}), ...data }
    if (!editChartElement(opened, slideIndex, elementId, patch)) throw new Error('pptx_chart_edit_failed')
  }
}
