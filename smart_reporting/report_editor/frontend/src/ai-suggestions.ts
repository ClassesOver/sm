import type { ChartDataProfile } from './api'

/**
 * Ask AI 推荐：只用服务端数据概况或正文表格本身做“是否值得推荐”的提示，
 * 不替代服务端校验；概况缺失时退回按图形推荐的通用建议。
 */

export type SuggestionKind = 'oneclick' | 'ai'

const TOP_FIVE = /前\s*5\s*(组|项)/

/** 按图形给出的基础建议叠加数据概况：先放数据相关的建议，再去掉明显不适用的。 */
export function chartSuggestionsFromProfile(base: string[], profile?: ChartDataProfile | null): string[] {
  if (!profile) return base
  const extra: string[] = []
  if (profile.categoryCount > 12) extra.push('将全部类别分页展示，保持统一颜色和值域')
  if (profile.unitCount >= 2) extra.push('不同单位的系列分别使用左右坐标轴并标明单位')
  if (profile.magnitudeRatio !== null && profile.magnitudeRatio >= 50 && !profile.hasNegative) {
    extra.push('数值差距很大，使用断轴让较小的值也能看清')
  }
  if (profile.hasPeriod) extra.push('标注最高和最低的期间')
  const kept = base.filter(command => !(TOP_FIVE.test(command) && profile.categoryCount <= 5))
  return [...new Set([...extra, ...kept])].slice(0, Math.max(base.length, 6))
}

/** 预设可能不适合当前数据的原因；仅作提示，仍允许尝试，最终以服务端核验为准。 */
export function presetCaution(presetId: string, profile?: ChartDataProfile | null): string | null {
  if (!profile) return null
  const numeric = profile.numericFieldCount
  switch (presetId) {
    case 'pie':
    case 'donut':
      return profile.hasNegative ? '数据含负值，不适合构成图' : null
    case 'radar':
      return numeric < 3 || numeric > 8 ? `需要 3–8 个数值字段，当前 ${numeric} 个` : null
    case 'scatter':
      return numeric < 2 ? `需要两个数值字段，当前 ${numeric} 个` : null
    case 'bubble':
      return numeric < 3 ? `需要三个数值字段，当前 ${numeric} 个` : null
    case 'heatmap':
      return profile.textFieldCount < 2 ? '需要两个分类字段' : null
    case 'bands':
      return numeric < 3 ? '需要中心值与上下界三个数值字段' : null
    case 'funnel':
      return profile.categoryCount < 3 ? '阶段少于 3 个' : null
    case 'dual':
    case 'dual-stack':
      return profile.unitCount < 2 ? '各系列单位一致，通常不需要双轴' : null
    case 'vertical-break':
    case 'horizontal-break':
      return profile.magnitudeRatio !== null && profile.magnitudeRatio < 10 ? '数值差距不大，通常不需要断轴' : null
    case 'pagination':
      return profile.categoryCount <= 20 ? `只有 ${profile.categoryCount} 个类别，通常无需分页` : null
    default:
      return null
  }
}

export const PRESET_GROUPS: readonly { title: string; ids: readonly string[] }[] = [
  { title: '换一种图形', ids: ['pie', 'donut', 'radar', 'funnel', 'sankey', 'scatter', 'bubble', 'heatmap', 'waterfall', 'boxplot', 'bands'] },
  { title: '单位或量级差异大', ids: ['dual', 'dual-stack', 'vertical-break', 'horizontal-break'] },
  { title: '类别太多', ids: ['pagination'] },
  { title: '排版与配色', ids: ['canvas'] },
]

export interface TableProfile { rowCount: number; columnCount: number; numericColumns: string[]; percentColumns: string[] }

/** 从正文 Markdown 表格直接统计行列与数值列，只用于推荐。 */
export function tableProfile(markdown: string): TableProfile | null {
  const lines = markdown.split('\n').map(line => line.trim()).filter(line => line.startsWith('|'))
  const rows = lines.filter(line => !/^\|?[\s:|-]+\|?$/.test(line))
    .map(line => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim()))
  if (rows.length < 2) return null
  const [header, ...body] = rows as [string[], ...string[][]]
  const numeric = (value: string) => /^[-+]?[\d,]+(\.\d+)?%?$/.test(value.replace(/\s/g, ''))
  const numericColumns = header.filter((_, index) => index > 0 && body.length > 0
    && body.every(row => !row[index] || row[index] === '-' || numeric(row[index]!)))
  const percentColumns = header.filter((name, index) => numericColumns.includes(name)
    && (/%|率|占比/.test(name) || body.some(row => row[index]?.endsWith('%'))))
  return { rowCount: body.length, columnCount: header.length, numericColumns, percentColumns }
}

export function tableSuggestions(profile: TableProfile | null): string[] {
  if (!profile) return ['按主要数值从高到低排序', '把数值统一保留两位小数', '精简列名，保持含义不变']
  const result: string[] = []
  const main = profile.numericColumns.find(name => !profile.percentColumns.includes(name)) ?? profile.numericColumns[0]
  if (main) result.push(`按「${main}」从高到低排序`)
  const rate = profile.percentColumns[0]
  if (rate) result.push(`标注「${rate}」低于 100% 的行`)
  if (profile.numericColumns.length && profile.rowCount > 1) result.push('在末尾增加合计行，比率列不直接相加')
  if (profile.rowCount > 15) result.push('只保留排名前 10 的行，并注明为子集')
  if (profile.columnCount > 6) result.push('精简列，只保留最关键的 5 列')
  result.push('把数值统一保留两位小数')
  return [...new Set(result)].slice(0, 4)
}

/** 首屏推荐条目：徽标明确区分“一键”（直接出预览）与“AI”（先填入要求）。 */
export function createSuggestionItem(options: {
  kind: SuggestionKind
  title: string
  detail?: string
  disabled?: boolean
  onClick: () => void
}): HTMLButtonElement {
  const item = document.createElement('button')
  item.type = 'button'
  item.className = 'ask-ai-start-item'
  item.dataset.kind = options.kind
  item.disabled = Boolean(options.disabled)
  const badge = document.createElement('span'); badge.className = 'ask-ai-start-badge'
  badge.textContent = options.kind === 'oneclick' ? '一键' : 'AI'
  const text = document.createElement('span'); text.className = 'ask-ai-start-text'
  const title = document.createElement('strong'); title.textContent = options.title
  text.append(title)
  if (options.detail) {
    const detail = document.createElement('span'); detail.className = 'ask-ai-start-detail'; detail.textContent = options.detail
    text.append(detail)
  }
  item.title = options.kind === 'oneclick' ? `${options.title}：立即生成预览，不经过 AI` : `${options.title}：填入下方要求，可补充后发送`
  item.append(badge, text)
  item.addEventListener('click', () => { if (!item.disabled) options.onClick() })
  return item
}

/** 首屏推荐区外壳；条目由各面板按自身数据填充。 */
export function createStartSection(moreAction?: { label: string; action: string; onClick: () => void }, failed = false) {
  const section = document.createElement('section')
  section.className = 'ask-ai-start'
  section.setAttribute('aria-label', '推荐操作')
  // 上一轮未完成时同样给出可直接点的替代方案，不让用户停在报错处。
  const heading = document.createElement('h3'); heading.textContent = failed ? '换个方式试试' : '从推荐开始'
  const hint = document.createElement('p'); hint.className = 'ask-ai-start-hint'
  hint.textContent = '「一键」立即出预览，不经过 AI；「AI」会先填入下方要求，可补充后发送。'
  const list = document.createElement('div'); list.className = 'ask-ai-start-list'
  section.append(heading, hint, list)
  if (moreAction) {
    const more = document.createElement('button')
    more.type = 'button'
    more.className = 'ask-ai-start-more'
    more.dataset.action = moreAction.action
    more.textContent = moreAction.label
    more.addEventListener('click', moreAction.onClick)
    section.append(more)
  }
  return { section, list }
}

export const CHART_REFINEMENTS = ['文字和标签再大一些', '换一组更清晰的配色', '标题再精简一些', '图例移到图表下方']
export const TABLE_REFINEMENTS = ['只保留最关键的列', '数值统一保留两位小数', '突出显示明显偏高或偏低的值', '按主要数值重新排序']

/** 继续调整时的常见微调：点击填入要求，不直接发送。 */
export function createRefinementRow(commands: readonly string[], fill: (command: string) => void): HTMLElement {
  const row = document.createElement('div')
  row.className = 'ask-ai-refine'
  row.setAttribute('role', 'group')
  row.setAttribute('aria-label', '常见微调')
  const label = document.createElement('span'); label.className = 'ask-ai-refine-label'; label.textContent = '常见微调'
  row.append(label)
  for (const command of commands) {
    const chip = document.createElement('button')
    chip.type = 'button'
    chip.className = 'ask-ai-refine-chip'
    chip.textContent = command
    chip.addEventListener('click', () => fill(command))
    row.append(chip)
  }
  return row
}
