import type { EditorView } from '@milkdown/kit/prose/view'
import { TABLE_PROTOCOL_EDIT_META } from './protocol-plugin'
import { buttonClasses } from './button'
import { askAIPanel } from './ask-ai-panel'
import { createAITemplateCard } from './ai-template-card'
import { type AIOrigin, TABLE_REFINEMENTS, createAITracker, createRefinementRow, createStartSection, createSuggestionItem, suggestionId, tableProfile, tableSuggestions } from './ai-suggestions'
import type { EditorTemplateInfo, ReportEditorClient, TableAIEditState } from './api'
import { markdownSha256 } from './source-validation'
import { formatElapsed } from './chart-ai-edit'
import { createElement, CircleAlert } from 'lucide'

/** 改表阶段：长标签作进度标题；时间线把 6 个细阶段收成 4 个粗阶段。 */
const TABLE_STAGE_LABELS: Record<string, string> = { queued: '排队中', plan: '正在理解要求并生成新表', check: '正在确认表格来源', validate: '正在核对数值与来源', compile: '正在生成新表', register: '即将完成' }
const TABLE_STAGE_GROUPS: { label: string; stages: string[] }[] = [
  // 服务端实际顺序为 plan → validate → register；新表在 plan 阶段生成。
  { label: '生成新表', stages: ['queued', 'plan', 'check', 'compile'] },
  { label: '核对来源', stages: ['validate'] },
  { label: '完成', stages: ['register'] },
]

const TABLE_MARKER = /^\[\[table:([A-Za-z0-9_.:-]+)\]\]$/
const CLOSE_MARKER = /^\[\[\/table:([A-Za-z0-9_.:-]+)\]\]$/

function text(value: string): Text { return document.createTextNode(value) }
function markdownTableRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/)
    .map(value => value.trim().replace(/\\\|/g, '|'))
}

function currentTablePreview(markdown: string): HTMLTableElement | null {
  const lines = markdown.split('\n').map(line => line.trim()).filter(line => line.startsWith('|'))
  if (!lines.length) return null
  const rows = lines.map(markdownTableRow)
  const hasSeparator = rows.length > 1 && rows[1]!.every(value => /^:?-{3,}:?$/.test(value))
  const header = rows[0]!
  const data = rows.slice(hasSeparator ? 2 : 1)
  const table = document.createElement('table')
  table.className = 'table-ai-current-preview'
  table.setAttribute('aria-label', '当前表格预览')
  const head = document.createElement('thead')
  const headRow = document.createElement('tr')
  header.forEach(value => {
    const cell = document.createElement('th')
    cell.scope = 'col'; cell.textContent = value; headRow.append(cell)
  })
  head.append(headRow); table.append(head)
  const body = document.createElement('tbody')
  data.forEach(values => {
    const row = document.createElement('tr')
    values.forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell) })
    body.append(row)
  })
  table.append(body)
  return table
}

/** 与后端 _TABLE_UNAVAILABLE_REASONS 对齐的不可用文案（预检展示用）。 */
const TABLE_UNAVAILABLE_REASONS: Record<string, string> = {
  read_only: '当前会话为只读分享会话，不能使用 AI 改表。',
  unconfigured: 'AI 改表服务未配置完成。',
  snapshot_expired: '该版本的数据来源已结束保留期，AI 改表不可用。',
  unknown_table: '表格不在当前版本的登记中。',
  table_unbound: '这张表没有登记单元格事实绑定（或来自旧报告），无法改表。',
  facts_missing: '该分析的事实文件不在登记中，AI 改表不可用。',
  facts_ambiguous: '该表跨越多个分析，暂不支持 AI 改表。',
  unavailable: 'AI 改表当前不可用。',
}

export function tableAiUnavailableReason(reason?: string): string {
  if (!reason) return TABLE_UNAVAILABLE_REASONS.unavailable
  return TABLE_UNAVAILABLE_REASONS[reason] ?? TABLE_UNAVAILABLE_REASONS.unavailable
}
function button(label: string, kind: 'primary' | 'secondary' | 'quiet', action: () => void, extraClass = ''): HTMLButtonElement {
  const node = document.createElement('button')
  node.type = 'button'
  node.className = [buttonClasses(kind), extraClass].filter(Boolean).join(' ')
  node.textContent = label
  node.addEventListener('click', action)
  return node
}

function tableNodes(view: EditorView, markdown: string): ReturnType<typeof view.state.schema.nodes.paragraph.create>[] {
  const lines = markdown.split('\n').filter(line => line.trim())
  const open = lines.find(line => TABLE_MARKER.test(line.trim())) ?? ''
  const close = lines.find(line => CLOSE_MARKER.test(line.trim())) ?? ''
  const start = lines.indexOf(open)
  const end = lines.indexOf(close)
  const tableLines = lines.slice(start + 1, end).filter(line => line.trim().startsWith('|'))
  const paragraph = view.state.schema.nodes.paragraph
  const table = view.state.schema.nodes.table
  const row = view.state.schema.nodes.table_row
  const cell = view.state.schema.nodes.table_cell
  const header = view.state.schema.nodes.table_header ?? cell
  const nodes: any[] = [paragraph.create(null, view.state.schema.text(open))]
  if (start > 0) nodes.splice(0, 0, paragraph.create(null, view.state.schema.text(lines.slice(0, start).join(' '))))
  if (table && row && cell && tableLines.length >= 2) {
    const parse = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(value => value.trim().replace(/\\([|`*_{}\[\]<>])/g, '$1'))
    const headerCells = parse(tableLines[0])
    const data = tableLines.slice(2).map(parse)
    const content = (value: string) => paragraph.create(null, value ? view.state.schema.text(value) : undefined)
    const rows = [
      row.create(null, headerCells.map(value => header.create(null, content(value)))),
      ...data.map(values => row.create(null, values.map(value => cell.create(null, content(value))))),
    ]
    nodes.push(table.create(null, rows))
  } else {
    tableLines.forEach(line => nodes.push(paragraph.create(null, view.state.schema.text(line))))
  }
  nodes.push(paragraph.create(null, view.state.schema.text(close)))
  return nodes
}

/** Replace one server-owned table protocol block in a single undoable transaction. */
export function replaceTableProtocolBlock(
  view: EditorView,
  tableId: string,
  markdown: string,
  existingCaption?: string | null,
): boolean {
  let from: number | null = null
  let to: number | null = null
  view.state.doc.descendants((node, pos) => {
    if (!node.isTextblock || from !== null) return true
    if (TABLE_MARKER.exec(node.textContent.trim())?.[1] !== tableId) return true
    from = pos
    view.state.doc.nodesBetween(pos + node.nodeSize, Math.min(view.state.doc.content.size, pos + node.nodeSize + 20000), (candidate, candidatePos) => {
      if (to !== null || !candidate.isTextblock) return true
      if (CLOSE_MARKER.exec(candidate.textContent.trim())?.[1] === tableId) to = candidatePos + candidate.nodeSize
      return to === null
    })
    return from === null
  })
  if (from === null || to === null) return false
  const replacementMarkers = markdown.match(/^\[\[table:([A-Za-z0-9_.:-]+)\]\]/m)
  const replacementTableId = replacementMarkers?.[1]
  if (!replacementTableId) return false
  const nodes = tableNodes(view, markdown)
  let replaceFrom = from as number
  const replaceTo = to as number
  // 服务端表题属于协议表格块，位于开始标记的紧邻上一段。替换包含新表题时一并
  // 覆盖旧表题，避免多轮改表把 caption 逐次堆叠在正文里。
  const replacementHasCaption = markdown.slice(0, markdown.indexOf(replacementMarkers[0])).trim().length > 0
  if (replacementHasCaption && existingCaption) {
    const before = view.state.doc.resolve(replaceFrom).nodeBefore
    if (before?.isTextblock && before.textContent.trim() === existingCaption.trim()) {
      replaceFrom -= before.nodeSize
    }
  }
  view.dispatch(view.state.tr.replaceWith(replaceFrom, replaceTo, nodes).setMeta(TABLE_PROTOCOL_EDIT_META, { tableId: replacementTableId }))
  return true
}

/** Extract the exact table body used by the server's table identity check. */
export function tableBodyMarkdown(markdown: string, tableId: string): string {
  const escaped = tableId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^\\[\\[table:${escaped}\\]\\]\\n(.*?)\\n\\n?\\[\\[/table:${escaped}\\]\\]$`, 'ms').exec(markdown)?.[1] ?? ''
}

/** 上下文预览：保留全部行，由滚动容器限制高度。 */
export function tablePreviewElement(markdown: string): { element: HTMLTableElement; meta: string } | null {
  const table = currentTablePreview(markdown)
  if (!table) return null
  return { element: table, meta: `共 ${table.tBodies[0]!.rows.length} 行 · ${table.tHead!.rows[0]!.cells.length} 列` }
}

export interface TableAIEditController { open(tableId: string, baseBody?: string): void; dispose(): void }

export function createTableAIEdit(options: {
  view: EditorView
  client: ReportEditorClient
  currentBody?: (tableId: string) => string
  pollIntervalMs?: number
  hooks?: { onReplaced?: (editId: string) => void; onError?: (code: string) => void }
}): TableAIEditController {
  const interval = options.pollIntervalMs ?? 800
  const tracker = createAITracker(options.client, 'table')
  let disposed = false
  let openedTableId: string | null = null
  let generation = 0
  let runningEditId: string | null = null
  let instructionDraft = ''
  let baselineBody = ''
  let latestBody = ''
  let inputPreviousEditId: string | undefined
  let progressClock: number | undefined
  const modal = askAIPanel().createSession({ kind: 'table', label: '表格', content: '<div class="table-ai-body" data-role="body"></div>' })
  const body = () => modal.card.querySelector<HTMLElement>('[data-role="body"]')!
  const invalidateCurrent = () => {
    generation++
    window.clearInterval(progressClock)
    if (runningEditId && openedTableId) void options.client.cancelTableAiEdit(openedTableId, runningEditId).catch(() => undefined)
    runningEditId = null
  }
  const poll = async (tableId: string, editId: string, owner: number, stage: HTMLElement, timeline: HTMLElement): Promise<TableAIEditState | null> => {
    while (!disposed && owner === generation) {
      await new Promise(resolve => setTimeout(resolve, interval))
      if (disposed || owner !== generation) return null
      const state = await options.client.tableAiEditStatus(tableId, editId)
      if (disposed || owner !== generation) return null
      stage.textContent = TABLE_STAGE_LABELS[state.stage ?? ''] ?? '正在处理表格'
      const currentIndex = TABLE_STAGE_GROUPS.findIndex(group => group.stages.includes(state.stage ?? ''))
      timeline.querySelectorAll<HTMLElement>('li').forEach((item, index) => {
        const stepState = currentIndex < 0 ? 'pending' : index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'pending'
        item.dataset.stepState = stepState
        item.querySelector('.ai-stage-dot')!.textContent = stepState === 'done' ? '✓' : ''
      })
      if (state.status === 'succeeded' || state.status === 'failed' || state.status === 'cancelled') return state
    }
    return null
  }
  /** 预检判定不可用时与改图一致地展示原因卡，不挂载输入区，避免提交后才失败。 */
  const renderUnavailable = (reason?: string) => {
    modal.setState('error')
    modal.mountComposer(null)
    const card = document.createElement('div')
    card.className = 'chart-ai-unavailable'
    card.setAttribute('role', 'alert')
    const icon = document.createElement('span')
    icon.className = 'chart-ai-unavailable-icon'
    icon.append(createElement(CircleAlert, { width: 22, height: 22, 'aria-hidden': 'true' }))
    const message = document.createElement('p')
    message.textContent = tableAiUnavailableReason(reason)
    const actions = document.createElement('div')
    actions.className = 'chart-ai-actions'
    actions.append(button('关闭', 'quiet', () => modal.close()))
    card.append(icon, message, actions)
    body().replaceChildren(card)
  }

  const input = async (tableId: string, targetTableId: string, baseBody: string, previousEditId?: string, note = '', failed = false, retainReview = false) => {
    if (disposed) return
    const owner = generation
    const focusInput = modal.visible && (body().contains(document.activeElement) || modal.composer.contains(document.activeElement) || document.activeElement === modal.closeButton)
    baselineBody = latestBody = baseBody
    inputPreviousEditId = previousEditId
    if (!retainReview) modal.setState(failed ? 'error' : 'idle')
    const context = document.createElement('div')
    context.className = 'ask-ai-context'
    const title = document.createElement('strong'); title.textContent = '当前表格'
    const preview = document.createElement('div'); preview.className = 'table-ai-preview-scroll'
    const previewData = tablePreviewElement(baseBody)
    if (previewData) {
      const meta = document.createElement('span'); meta.className = 'ai-mini-meta'; meta.textContent = previewData.meta
      const headRow = document.createElement('div'); headRow.className = 'ai-mini-head'; headRow.append(title, meta)
      preview.append(previewData.element)
      context.append(headRow, preview)
    } else {
      const empty = document.createElement('p'); empty.textContent = '已选中正文表格'; preview.append(empty)
      context.append(title, preview)
    }
    if (!retainReview) body().replaceChildren(context)
    let retryButton: HTMLButtonElement | undefined
    if (note) {
      const status = document.createElement('p'); status.className = 'chart-ai-note'; if (failed) status.dataset.tone = 'warn'; status.setAttribute('role', 'status'); status.textContent = note; body().append(status)
      if (failed && instructionDraft.trim()) {
        retryButton = document.createElement('button'); retryButton.type = 'button'; retryButton.className = buttonClasses('secondary'); retryButton.textContent = '重新生成'
        body().append(retryButton)
      }
    }
    const suggestions = tableSuggestions(tableProfile(baseBody))
    const area = document.createElement('textarea')
    area.id = `table-ai-input${modal.idSuffix}`; area.maxLength = 2000; area.rows = 3
    area.placeholder = `例如：${suggestions[0] ?? '按同比增幅从高到低排列并标注低于100%的项目'}`
    area.value = instructionDraft
    const fill = (command: string, source: AIOrigin['source']) => {
      const merged = area.value.trim() ? `${area.value.trim()}；${command}` : command
      area.value = merged.slice(0, 2000)
      area.dispatchEvent(new Event('input'))
      area.focus()
      tracker.used({ source, kind: 'ai', suggestionId: suggestionId(command), text: command })
    }
    // 全部模板（一键）折叠在首屏推荐下方；推荐区已给出最匹配的一项。
    const templateDetails = document.createElement('details'); templateDetails.className = 'chart-ai-standard'
    const summary = document.createElement('summary'); summary.textContent = '全部模板（一键，立即出预览）'
    const templateRoot = document.createElement('div'); templateRoot.className = 'table-ai-templates'; templateDetails.append(summary, templateRoot)
    const skeleton = document.createElement('div'); skeleton.className = 'ai-template-skeleton'; skeleton.setAttribute('aria-hidden', 'true')
    skeleton.append(document.createElement('span'), document.createElement('span')); templateRoot.append(skeleton)
    const start = createStartSection({ label: '查看全部模板', action: 'show-table-templates', onClick: () => {
      templateDetails.open = true
      templateDetails.scrollIntoView?.({ block: 'nearest' })
      templateRoot.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus()
    } }, failed)
    const startTemplate = document.createElement('div'); startTemplate.className = 'ask-ai-start-slot'
    start.list.append(startTemplate)
    for (const command of suggestions.slice(0, 3)) start.list.append(createSuggestionItem({ kind: 'ai', title: command, onClick: () => fill(command, 'start') }))
    const label = document.createElement('label'); label.htmlFor = area.id; label.textContent = retainReview ? '继续调整新表' : '描述你的修改'
    const form = document.createElement('div'); form.className = 'ask-ai-input-form'
    if (!retainReview) body().append(start.section)
    body().append(templateDetails)
    form.append(label)
    if (retainReview) form.append(createRefinementRow(TABLE_REFINEMENTS, command => fill(command, 'refine')))
    form.append(area)
    const actions = document.createElement('div'); actions.className = 'chart-ai-actions'
    const submit = button('让 AI 修改', 'primary', () => { const instruction = area.value.trim(); if (instruction) void runEdit(tableId, targetTableId, instruction, baseBody, previousEditId) })
    retryButton?.addEventListener('click', () => { if (!submit.disabled) submit.click() })
    const count = document.createElement('span'); count.className = 'chart-ai-hint'
    actions.append(submit, count); form.append(actions)
    const hint = document.createElement('p'); hint.className = 'chart-ai-hint'; hint.textContent = 'Ctrl / ⌘ + Enter 发送 · 只使用已登记数据，生成后可逐格查看来源'
    form.append(hint)
    modal.mountComposer(form)
    const syncInput = () => {
      instructionDraft = area.value
      area.style.height = 'auto'
      area.style.height = `${Math.min(area.scrollHeight, 160)}px`
      submit.disabled = !area.value.trim()
      count.textContent = `${area.value.length} / 2000`
      count.dataset.level = area.value.length >= 2000 ? 'limit' : area.value.length >= 1800 ? 'warn' : ''
    }
    area.addEventListener('input', syncInput)
    area.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); if (!submit.disabled) submit.click() }
    })
    syncInput()
    let templateLoadFailed = false
    void options.client.tableTemplates(tableId).catch(() => { templateLoadFailed = true; return { templates: [] as EditorTemplateInfo[] } }).then(templates => {
      skeleton.remove()
      if (disposed || owner !== generation || !area.isConnected) return
      const ordered = [...templates.templates].sort((a, b) => Number(b.recommended ?? false) - Number(a.recommended ?? false) || Number(b.available) - Number(a.available))
      const applyTemplate = (item: EditorTemplateInfo, source: AIOrigin['source']) => {
        tracker.used({ source, kind: 'oneclick', suggestionId: `template-${item.templateId}` })
        void runEdit(tableId, targetTableId, `套用模板：${item.name}`, baseBody, previousEditId, item.templateId)
      }
      ordered.forEach(item => templateRoot.append(createAITemplateCard(item, 'table', () => applyTemplate(item, 'dialog'))))
      const featured = ordered.find(item => item.available)
      if (featured) startTemplate.replaceWith(createSuggestionItem({ kind: 'oneclick', title: featured.name,
        detail: featured.recommended ? (featured.recommendationReason || '与当前数据最匹配') : '预制模板', onClick: () => applyTemplate(featured, 'start') }))
      if (!templates.templates.length) {
        if (templateLoadFailed) {
          const loadNote = document.createElement('p'); loadNote.className = 'chart-ai-hint'; loadNote.textContent = '模板加载失败，可直接输入要求生成。'
          templateRoot.append(loadNote)
        } else templateDetails.hidden = true
      }
    })
    if (focusInput) area.focus()
  }
  const review = (tableId: string, targetTableId: string, result: TableAIEditState, baseBody: string, instruction: string) => {
    modal.setState('ready')
    modal.addMessage('assistant', '新表已生成。')
    body().replaceChildren(text(`要求：${instruction}`))
    // 审阅摘要与行位移（纯数据先算）：按行标签把新表行对回原表行序。
    const reviewRows = result.review?.rows ?? []
    const baseLabels = (() => {
      const lines = baseBody.split('\n').map(line => line.trim()).filter(line => line.startsWith('|'))
      const rows = lines.filter(line => !/^\|?[\s:|-]+\|?$/.test(line)).map(line => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(value => value.trim()))
      return rows.slice(1).map(row => row[0] ?? '')
    })()
    const usedBase = new Set<number>()
    const shifts = reviewRows.map((row, index) => {
      const baseIndex = baseLabels.findIndex((label, j) => label === row.label && !usedBase.has(j))
      if (baseIndex < 0) return 0
      usedBase.add(baseIndex)
      return index - baseIndex
    })
    const cellCounts = { added: 0, changed: 0, flagged: 0 }
    for (const row of reviewRows) for (const cell of row.cells) {
      if (cell.status === 'added') cellCounts.added += 1
      else if (cell.status === 'changed') cellCounts.changed += 1
      else if (cell.status === 'flagged') cellCounts.flagged += 1
    }
    const summaryParts: [string, string, string][] = []
    if (cellCounts.added) summaryParts.push(['is-added', `新增 ${cellCounts.added} 格`, '.table-ai-review'])
    if (cellCounts.changed) summaryParts.push(['is-changed', `变化 ${cellCounts.changed} 格`, '.table-ai-review'])
    if (cellCounts.flagged) summaryParts.push(['is-flagged', `标注 ${cellCounts.flagged} 格`, '.table-ai-review'])
    const movedCount = shifts.filter(shift => shift !== 0).length
    if (movedCount) summaryParts.push(['is-moved', `行移动 ${movedCount}`, '.table-ai-review'])
    const deletedCount = baseLabels.length - usedBase.size
    if (deletedCount) summaryParts.push(['is-deleted', `删除 ${deletedCount} 行`, '.table-ai-review'])
    if (result.warnings?.length) summaryParts.push(['is-warn', `告警 ${result.warnings.length} 条`, '.ai-alert-note'])
    if (result.skipped?.length) summaryParts.push(['is-skipped', `未执行 ${result.skipped.length} 项`, '.chart-ai-note'])
    const summary = document.createElement('div')
    summary.className = 'ai-review-summary'
    summary.setAttribute('aria-label', '审阅摘要')
    if (!summaryParts.length) {
      const item = document.createElement('span')
      item.className = 'ai-review-summary-item'
      item.textContent = '无单元格变化'
      summary.append(item)
    }
    for (const [tone, label, selector] of summaryParts) {
      const item = document.createElement('button')
      item.type = 'button'
      item.className = tone ? `ai-review-summary-item ${tone}` : 'ai-review-summary-item'
      item.textContent = label
      item.title = '定位到对应内容'
      item.addEventListener('click', () => {
        const target = body().querySelector<HTMLElement>(selector)
        if (!target) return
        target.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        target.classList.remove('ai-flash')
        void target.offsetWidth
        target.classList.add('ai-flash')
        window.setTimeout(() => target.classList.remove('ai-flash'), 2000)
      })
      summary.append(item)
    }
    body().append(summary)
    // 逐格审阅（设计稿 §14.1）：新增/标注/未变着色；点击数据格查看来源。
    const grid = document.createElement('table')
    grid.className = 'table-ai-review'
    const head = document.createElement('thead')
    const headRow = document.createElement('tr')
    const corner = document.createElement('th')
    corner.setAttribute('scope', 'col'); corner.textContent = ''
    headRow.append(corner)
    for (const column of result.review?.columns ?? []) {
      const th = document.createElement('th')
      th.setAttribute('scope', 'col'); th.append(text(column))
      headRow.append(th)
    }
    head.append(headRow); grid.append(head)
    const detail = document.createElement('p')
    detail.className = 'table-ai-source-detail'
    detail.setAttribute('role', 'status')
    let selectedCell: HTMLButtonElement | null = null
    const showSource = (label: string, column: string, source: { analysisId: string; factIds: string[]; selector: string | null } | undefined, control?: HTMLButtonElement) => {
      if (selectedCell && selectedCell !== control) { selectedCell.removeAttribute('aria-pressed'); selectedCell.classList.remove('is-selected') }
      selectedCell = control ?? null
      if (control) { control.setAttribute('aria-pressed', 'true'); control.classList.add('is-selected') }
      detail.textContent = source
        ? `「${label} / ${column}」来源：${source.analysisId}${source.selector ? ` · ${source.selector}` : ''}${source.factIds.length ? ` · ${source.factIds.join('、')}` : ''}`
        : `「${label} / ${column}」未绑定来源（行标签或派生列，数值见登记事实）。`
      detail.animate?.([{ opacity: 0.35 }, { opacity: 1 }], { duration: 160 })
    }
    const gridBody = document.createElement('tbody')
    for (const [rowIndex, row] of reviewRows.entries()) {
      const tr = document.createElement('tr')
      const th = document.createElement('th')
      th.setAttribute('scope', 'row'); th.append(text(row.label))
      const shift = shifts[rowIndex] ?? 0
      if (shift !== 0) {
        const badge = document.createElement('span')
        badge.className = 'table-ai-row-shift'
        badge.textContent = shift > 0 ? `↓${shift}` : `↑${-shift}`
        badge.title = `原第 ${rowIndex - shift + 1} 行，移到第 ${rowIndex + 1} 行`
        badge.setAttribute('aria-label', badge.title)
        th.append(badge)
      }
      tr.append(th)
      for (const cell of row.cells) {
        const td = document.createElement('td')
        td.className = `table-ai-cell-${cell.status}`
        const control = document.createElement('button')
        control.type = 'button'
        control.className = 'table-ai-cell'
        control.append(text(cell.text))
        control.setAttribute('aria-label', `${row.label} ${cell.column}：${cell.text}（${cell.status}，查看来源）`)
        control.addEventListener('click', () => showSource(row.label, cell.column, cell.source, control))
        td.append(control)
        tr.append(td)
      }
      gridBody.append(tr)
    }
    grid.addEventListener('keydown', event => {
      if (!(event.target instanceof HTMLButtonElement) || !event.target.classList.contains('table-ai-cell')) return
      if (!['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'].includes(event.key)) return
      const columns = result.review?.columns.length ?? 0
      if (!columns) return
      const cells = [...grid.querySelectorAll<HTMLButtonElement>('.table-ai-cell')]
      const index = cells.indexOf(event.target)
      if (index < 0) return
      const next = event.key === 'ArrowRight' ? index + 1
        : event.key === 'ArrowLeft' ? index - 1
        : event.key === 'ArrowDown' ? index + columns : index - columns
      if (next < 0 || next >= cells.length) return
      event.preventDefault()
      cells[next]!.focus()
      cells[next]!.click()
    })
    grid.append(gridBody)
    const legend = document.createElement('div')
    legend.className = 'table-ai-legend'
    legend.setAttribute('aria-label', '单元格状态图例')
    for (const [status, label] of [['added', '新增'], ['changed', '值已变化'], ['flagged', '已标注'], ['', '未变']] as const) {
      const item = document.createElement('span')
      const dot = document.createElement('i')
      dot.className = status ? `table-ai-legend-dot table-ai-cell-${status}` : 'table-ai-legend-dot'
      item.append(dot, text(label))
      legend.append(item)
    }
    body().append(legend)
    body().append(grid)
    detail.textContent = '点击格子查看来源。'
    body().append(detail)
    const originalData = tablePreviewElement(baseBody)
    if (originalData) {
      const originalDetails = document.createElement('details')
      originalDetails.className = 'chart-ai-standard'
      const originalSummary = document.createElement('summary'); originalSummary.textContent = '查看原表（替换前）'
      originalDetails.append(originalSummary, originalData.element)
      body().append(originalDetails)
    }
    ;(result.warnings ?? []).forEach(warning => { const item = document.createElement('p'); item.className = 'ai-alert-note'; item.setAttribute('role', 'alert'); item.append(text(warning)); body().append(item) })
    ;(result.skipped ?? []).forEach(item => { const note = document.createElement('p'); note.className = 'chart-ai-note'; note.textContent = `「${item.request}」未执行：${item.reason}`; body().append(note) })
    const actions = document.createElement('div'); actions.className = 'chart-ai-actions'
    const pending = document.createElement('p'); pending.className = 'ask-ai-adopt-note'; pending.textContent = '尚未修改正文'; actions.append(pending)
    actions.append(button('采用到正文', 'primary', () => {
      const currentBody = options.currentBody?.(targetTableId) ?? latestBody
      if (currentBody !== baseBody) {
        void input(tableId, targetTableId, currentBody, undefined, '正文表格已改变，未覆盖新内容。已读取最新表格，请重新生成。', true)
        return
      }
      if (!result.markdown || !replaceTableProtocolBlock(options.view, targetTableId, result.markdown, result.baseCaption)) {
        detail.textContent = '未能定位完整原表，尚未替换。请回到正文重新选择表格。'
        options.hooks?.onError?.('report_editor_table_ai_target_missing'); return
      }
      options.hooks?.onReplaced?.(result.editId); tracker.adopted('accepted'); openedTableId = null
      const newTableId = TABLE_MARKER.exec(result.markdown.split('\n').find(line => TABLE_MARKER.test(line)) ?? '')?.[1]
      const locateBlock = () => {
        if (!newTableId) return null
        const starts: { pos: number; size: number }[] = []; const ends: number[] = []
        options.view.state.doc.descendants((node, pos) => {
          if (!node.isTextblock) return
          if (node.textContent === `[[table:${newTableId}]]`) starts.push({ pos, size: node.nodeSize })
          if (node.textContent === `[[/table:${newTableId}]]`) ends.push(pos + node.nodeSize)
        })
        return starts.length === 1 && ends.length === 1 && ends[0]! > starts[0]!.pos
          ? { from: starts[0]!.pos, tablePos: starts[0]!.pos + starts[0]!.size, to: ends[0]! } : null
      }
      const adopted = locateBlock()
      const adoptedContent = adopted ? options.view.state.doc.slice(adopted.from, adopted.to).content : null
      modal.notifyReplaced({
        locate: () => {
          const current = locateBlock()
          if (!current || !adoptedContent?.eq(options.view.state.doc.slice(current.from, current.to).content)) return false
          const element = options.view.nodeDOM(current.tablePos)
          if (!(element instanceof HTMLElement) || !element.isConnected) return false
          element.scrollIntoView?.({ block: 'center', behavior: 'auto' })
          return true
        },
        continueEditing: () => {
          if (!newTableId) return
          openedTableId = newTableId
          void input(tableId, newTableId, tableBodyMarkdown(result.markdown!, newTableId), result.editId)
        },
      })
    }))
    actions.append(button('继续调整', 'secondary', () => modal.focusComposer()))
    actions.append(button('放弃', 'quiet', () => { tracker.adopted('discarded'); openedTableId = null; modal.setState('idle'); modal.mountComposer(null); body().replaceChildren(text('已放弃本轮结果。继续编辑时，请在正文选择表格。')); modal.close() }))
    body().append(actions)
    modal.mountReviewActions(actions)
    const keyHint = document.createElement('p')
    keyHint.className = 'chart-ai-hint'
    keyHint.innerHTML = '快捷键：<kbd>A</kbd> 采用 · <kbd>C</kbd> 继续调整 · <kbd>X</kbd> 放弃（输入时不触发）'
    body().append(keyHint)
    // 审阅快捷键：监听挂 document，进入其他阶段/会话后自清理。
    const reviewBody = body()
    const [acceptBtn, continueBtn, discardBtn] = [...actions.querySelectorAll('button')]
    for (const [actionButton, key] of [[acceptBtn, 'A'], [continueBtn, 'C'], [discardBtn, 'X']] as const) {
      if (actionButton) actionButton.dataset.key = key
    }
    const onReviewKey = (event: KeyboardEvent) => {
      if (!reviewBody.isConnected || !acceptBtn || !reviewBody.contains(acceptBtn)) { document.removeEventListener('keydown', onReviewKey); return }
      if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return
      if ((event.target as HTMLElement | null)?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (reviewBody.closest('[hidden]')) return
      const key = event.key.toLowerCase()
      const target = key === 'a' ? acceptBtn : key === 'c' ? continueBtn : key === 'x' ? discardBtn : undefined
      if (!target) return
      event.preventDefault()
      target.click()
    }
    document.addEventListener('keydown', onReviewKey)
    instructionDraft = ''
    void input(tableId, targetTableId, baseBody, result.editId, '', false, true)
  }
  const runEdit = async (tableId: string, targetTableId: string, instruction: string, baseBody: string, previousEditId?: string, templateId?: string) => {
    const owner = generation
    if (!templateId) instructionDraft = instruction
    const currentBody = options.currentBody?.(targetTableId) ?? latestBody
    if (currentBody !== baseBody) {
      await input(tableId, targetTableId, currentBody, undefined, '正文表格已更新，已保留要求。请核对后重新生成。')
      return
    }
    modal.addMessage('user', instruction)
    modal.setState('running')
    tracker.started(templateId ? undefined : instruction)
    const progress = document.createElement('div'); progress.className = 'ask-ai-progress'
    const stage = document.createElement('p'); stage.className = 'chart-ai-stage'; stage.setAttribute('role', 'status'); stage.textContent = '正在准备表格改动…'
    const track = document.createElement('div'); track.className = 'ai-progress-track'; track.setAttribute('aria-hidden', 'true')
    const fill = document.createElement('span'); fill.className = 'ai-progress-fill'; track.append(fill)
    const timeline = document.createElement('ol'); timeline.className = 'ai-stage-timeline'; timeline.setAttribute('aria-label', '生成阶段')
    TABLE_STAGE_GROUPS.forEach((group, index) => {
      const item = document.createElement('li'); item.dataset.stepState = index === 0 ? 'current' : 'pending'
      const dot = document.createElement('span'); dot.className = 'ai-stage-dot'; dot.setAttribute('aria-hidden', 'true')
      item.append(dot, text(group.label)); timeline.append(item)
    })
    const elapsed = document.createElement('p'); elapsed.className = 'ask-ai-elapsed'; elapsed.setAttribute('aria-hidden', 'true'); elapsed.textContent = '已用时 00:00'
    const startedAt = performance.now()
    const clock = progressClock = window.setInterval(() => { elapsed.textContent = `已用时 ${formatElapsed(performance.now() - startedAt)}` }, 1000)
    const hint = document.createElement('p'); hint.className = 'chart-ai-hint'; hint.textContent = '通常需要 20–60 秒。可以收起侧栏继续改正文，完成后会提示你。'
    const cancel = button('取消改表', 'secondary', () => { tracker.finished('cancelled'); invalidateCurrent(); void input(tableId, targetTableId, baseBody, previousEditId, '已取消本次改表。') })
    progress.append(stage, track, timeline, elapsed, hint, cancel); body().replaceChildren(progress)
    try {
      const expectedSha256 = await markdownSha256(baseBody)
      if (owner !== generation || disposed) return
      const payload = { baseBody, previousEditId, expectedSha256 }
      const started = templateId ? await options.client.startTableTemplateEdit(tableId, { ...payload, templateId }) : await options.client.startTableAiEdit(tableId, { ...payload, instruction })
      if (owner !== generation || disposed) { void options.client.cancelTableAiEdit(tableId, started.editId).catch(() => undefined); return }
      runningEditId = started.editId
      const result = await poll(tableId, started.editId, owner, stage, timeline)
      if (!result) return
      tracker.finished(result.status === 'succeeded' ? 'succeeded' : result.status === 'cancelled' ? 'cancelled' : 'failed', result.error?.code)
      if (result.status === 'succeeded') review(tableId, targetTableId, result, baseBody, instruction)
      else await input(tableId, targetTableId, baseBody, previousEditId, result.error?.message ?? '改表未完成，原表保持不变。', result.status === 'failed')
    } catch {
      tracker.finished('failed', 'request_failed')
      if (owner === generation && !disposed) await input(tableId, targetTableId, baseBody, previousEditId, '改表请求失败，原表保持不变。', true)
    } finally {
      window.clearInterval(clock)
      if (owner === generation) runningEditId = null
    }
  }
  return {
    open(targetTableId, baseBody) {
      const nextBody = baseBody ?? options.currentBody?.(targetTableId) ?? (openedTableId === targetTableId ? latestBody : '')
      if (openedTableId === targetTableId) {
        latestBody = nextBody
        if (nextBody !== baselineBody) {
          if (modal.state === 'idle' || modal.state === 'error') void input(targetTableId, targetTableId, nextBody, inputPreviousEditId, '已读取更新后的表格，改表要求已保留。')
          else modal.addMessage('assistant', '正文表格已变化。当前任务和预览已保留，替换前会核验是否仍匹配。')
        }
        modal.open(); return
      }
      invalidateCurrent()
      const owner = generation
      openedTableId = targetTableId
      baselineBody = latestBody = nextBody
      instructionDraft = ''
      modal.setLabel(nextBody.split('\n')[0]?.replace(/\|/g, ' ').trim().slice(0, 48) || '正文表格')
      modal.card.querySelector('.ask-ai-messages')?.replaceChildren()
      const loading = document.createElement('p'); loading.className = 'ai-loading-line'; loading.textContent = '正在读取表格信息…'
      body().replaceChildren(loading)
      modal.mountComposer(null)
      modal.open()
      // 与改图对齐：打开时并行预检可用性，不可用直接展示原因卡；预检请求失败则照常进输入区，由生成环节兜底报错。
      const availabilityRequest = typeof options.client.tableAiAvailability === 'function'
        ? options.client.tableAiAvailability(targetTableId).catch(() => null)
        : Promise.resolve(null)
      void Promise.allSettled([options.client.tableEditRecordByTableId(targetTableId), availabilityRequest])
        .then(([recordResult, availabilityResult]) => {
          if (disposed || owner !== generation) return
          const availability = availabilityResult.status === 'fulfilled' ? availabilityResult.value : null
          if (availability && !availability.available) { renderUnavailable(availability.reason); return }
          const record = recordResult.status === 'fulfilled' ? recordResult.value : undefined
          void input(targetTableId, targetTableId, latestBody, record?.editId)
        })
    },
    dispose() { disposed = true; invalidateCurrent(); modal.remove() },
  }
}
