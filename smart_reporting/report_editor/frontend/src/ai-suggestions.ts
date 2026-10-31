import type { ChartRecommendations } from './api'

/**
 * Ask AI 推荐：改图推荐由服务端按已核验作图数据给出，这里只负责合并与展示；
 * 改表推荐依赖用户正在编辑的正文表格，仍在前端按表格内容生成。
 */

export type SuggestionKind = 'oneclick' | 'ai'

/**
 * 合并服务端推荐与按图形的通用建议：服务端建议在前，被服务端标为不适用的通用建议去掉。
 * 服务端未返回推荐（旧服务或概况不可用）时只展示通用建议，前端不另行推断数据。
 */
export function mergeChartSuggestions(base: string[], recommendations?: ChartRecommendations | null): { id: string; text: string }[] {
  const suppressed = new Set(recommendations?.suppress ?? [])
  const merged = [...(recommendations?.suggestions ?? []),
    ...base.map(text => ({ id: suggestionId(text), text })).filter(item => !suppressed.has(item.id))]
  const seen = new Set<string>()
  return merged.filter(item => !seen.has(item.text) && Boolean(seen.add(item.text))).slice(0, Math.max(base.length, 6))
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

export type AIEventSource = 'start' | 'dialog' | 'refine' | 'free'
export interface AIOrigin { source: AIEventSource; kind: SuggestionKind; suggestionId?: string; /** 仅本地判断归因，不上报。 */ text?: string }

const SUGGESTION_KEYWORDS: [RegExp, string][] = [
  [/分页/, 'paginate'], [/左右坐标轴|双坐标轴/, 'dual-axis'], [/断轴/, 'break'], [/最高和最低/, 'mark-extremes'],
  [/数值标签/, 'value-labels'], [/前\s*5/, 'top5'], [/横向条形/, 'to-barh'], [/降序|从大到小|从高到低/, 'sort'],
  [/标题/, 'title'], [/配色/, 'palette'], [/图例/, 'legend'], [/平滑|加粗/, 'line-style'], [/柱状图对比/, 'to-bar'],
  [/百分比/, 'percent'], [/文字和标签/, 'font-size'],
  [/低于\s*100%/, 'flag-rate'], [/合计行/, 'total-row'], [/前\s*10/, 'top10'], [/关键.*列|精简列/, 'trim-columns'],
  [/两位小数/, 'decimals'], [/偏高或偏低/, 'outliers'], [/列名/, 'rename-columns'],
]

/** 推荐的稳定标识：只用固定词表，不上报建议原文（改表建议含真实列名）。 */
export function suggestionId(command: string): string {
  return SUGGESTION_KEYWORDS.find(([pattern]) => pattern.test(command))?.[1] ?? 'other'
}

const safeId = (value: string) => value.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'other'

/**
 * Ask AI 使用情况埋点：推荐被点击、发起修改、结果与是否采用。只上报枚举与固定标识，
 * 上报失败静默忽略，不影响编辑流程。
 */
export function createAITracker(client: unknown, surface: 'chart' | 'table') {
  const report = (payload: Record<string, unknown>) => {
    const send = (client as { reportEvent?: (body: Record<string, unknown>) => Promise<void> } | null)?.reportEvent
    if (typeof send !== 'function') return
    void Promise.resolve().then(() => send.call(client, { surface, ...payload })).catch(() => undefined)
  }
  const fields = (origin: AIOrigin) => ({ source: origin.source, kind: origin.kind,
    ...(origin.suggestionId ? { suggestionId: safeId(origin.suggestionId) } : {}) })
  let pending: AIOrigin | null = null
  let active: (AIOrigin & { startedAt: number }) | null = null
  return {
    used(origin: AIOrigin) {
      pending = origin
      report({ event: 'ai_suggestion_used', ...fields(origin) })
    },
    started(instruction?: string) {
      // 推荐文字已被用户删掉重写时，归为自由输入。
      const origin = pending && !(pending.kind === 'ai' && pending.text && instruction && !instruction.includes(pending.text))
        ? pending : { source: 'free' as const, kind: 'ai' as const }
      pending = null
      active = { ...origin, startedAt: performance.now() }
      report({ event: 'ai_edit_started', ...fields(origin) })
    },
    finished(outcome: 'succeeded' | 'failed' | 'cancelled', errorCode?: string) {
      if (!active) return
      report({ event: 'ai_edit_finished', ...fields(active), outcome,
        durationMs: Math.max(0, Math.round(performance.now() - active.startedAt)),
        ...(errorCode ? { errorCode: errorCode.slice(0, 128) } : {}) })
      if (outcome !== 'succeeded') active = null
    },
    adopted(outcome: 'accepted' | 'discarded') {
      if (!active) return
      report({ event: 'ai_edit_adopted', ...fields(active), outcome })
      active = null
    },
  }
}
