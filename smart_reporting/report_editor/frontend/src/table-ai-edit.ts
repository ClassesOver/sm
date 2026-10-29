import type { EditorView } from '@milkdown/kit/prose/view'
import { TABLE_PROTOCOL_EDIT_META } from './protocol-plugin'
import { buttonClasses } from './button'
import { askAIPanel } from './ask-ai-panel'
import { createAITemplateCard } from './ai-template-card'
import type { EditorTemplateInfo, ReportEditorClient, TableAIEditState } from './api'
import { markdownSha256 } from './source-validation'

const TABLE_MARKER = /^\[\[table:([A-Za-z0-9_.:-]+)\]\]$/
const CLOSE_MARKER = /^\[\[\/table:([A-Za-z0-9_.:-]+)\]\]$/

function text(value: string): Text { return document.createTextNode(value) }
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

export interface TableAIEditController { open(tableId: string, baseBody?: string): void; dispose(): void }

export function createTableAIEdit(options: {
  view: EditorView
  client: ReportEditorClient
  currentBody?: (tableId: string) => string
  pollIntervalMs?: number
  hooks?: { onReplaced?: (editId: string) => void; onError?: (code: string) => void }
}): TableAIEditController {
  const interval = options.pollIntervalMs ?? 800
  let disposed = false
  let openedTableId: string | null = null
  let generation = 0
  let runningEditId: string | null = null
  let instructionDraft = ''
  let baselineBody = ''
  let latestBody = ''
  let inputPreviousEditId: string | undefined
  let progressClock: number | undefined
  const modal = askAIPanel().createSession({ kind: 'table', label: '表格', content: '<div class="panel-header"><h2>AI 改表</h2></div><div class="table-ai-body" data-role="body"></div>' })
  const body = () => modal.card.querySelector<HTMLElement>('[data-role="body"]')!
  const invalidateCurrent = () => {
    generation++
    window.clearInterval(progressClock)
    if (runningEditId && openedTableId) void options.client.cancelTableAiEdit(openedTableId, runningEditId).catch(() => undefined)
    runningEditId = null
  }
  const poll = async (tableId: string, editId: string, owner: number, stage: HTMLElement): Promise<TableAIEditState | null> => {
    while (!disposed && owner === generation) {
      await new Promise(resolve => setTimeout(resolve, interval))
      if (disposed || owner !== generation) return null
      const state = await options.client.tableAiEditStatus(tableId, editId)
      if (disposed || owner !== generation) return null
      const labels: Record<string, string> = { queued: '排队中', plan: '正在理解改表要求', check: '正在核验来源', validate: '正在核验表格与来源', compile: '正在生成表格', register: '正在登记结果' }
      stage.textContent = labels[state.stage ?? ''] ?? '正在处理表格'
      if (state.status === 'succeeded' || state.status === 'failed' || state.status === 'cancelled') return state
    }
    return null
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
    const preview = document.createElement('pre'); preview.textContent = baseBody.split('\n').slice(0, 5).join('\n') || '已选中正文表格'
    context.append(title, preview)
    if (!retainReview) body().replaceChildren(context)
    if (note) { const status = document.createElement('p'); status.className = 'chart-ai-note'; status.setAttribute('role', 'status'); status.textContent = note; body().append(status) }
    const area = document.createElement('textarea')
    area.id = `table-ai-input${modal.idSuffix}`; area.maxLength = 2000; area.rows = 3
    area.placeholder = '例如：按同比增幅从高到低排列并标注低于100%的项目'
    area.value = instructionDraft
    const templateDetails = document.createElement('details'); templateDetails.className = 'chart-ai-standard'
    const summary = document.createElement('summary'); summary.textContent = '模板与快捷调整'
    const templateRoot = document.createElement('div'); templateRoot.className = 'table-ai-templates'; templateDetails.append(summary, templateRoot)
    const label = document.createElement('label'); label.htmlFor = area.id; label.textContent = retainReview ? '继续调整新表' : '改表要求'
    const form = document.createElement('div'); form.className = 'ask-ai-input-form'
    body().append(templateDetails)
    form.append(label, area)
    const actions = document.createElement('div'); actions.className = 'chart-ai-actions'
    const submit = button('生成改表', 'primary', () => { const instruction = area.value.trim(); if (instruction) void runEdit(tableId, targetTableId, instruction, baseBody, previousEditId) })
    const count = document.createElement('span'); count.className = 'chart-ai-hint'
    actions.append(submit, count); form.append(actions)
    const hint = document.createElement('p'); hint.className = 'chart-ai-hint'; hint.textContent = 'Ctrl / ⌘ + Enter 发送 · 生成后可逐格查看来源'
    form.append(hint)
    modal.mountComposer(form)
    const syncInput = () => { instructionDraft = area.value; submit.disabled = !area.value.trim(); count.textContent = `${area.value.length} / 2000` }
    area.addEventListener('input', syncInput)
    area.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); if (!submit.disabled) submit.click() }
    })
    syncInput()
    void options.client.tableTemplates(tableId).catch(() => ({ templates: [] as EditorTemplateInfo[] })).then(templates => {
      if (disposed || owner !== generation || !area.isConnected) return
      templates.templates.forEach(item => {
        const node = createAITemplateCard(item, 'table', () => void runEdit(tableId, targetTableId, `套用模板：${item.name}`, baseBody, previousEditId, item.templateId))
        templateRoot.append(node)
      })
      if (!templates.templates.length) { templateDetails.hidden = true }
    })
    if (focusInput) area.focus()
  }
  const review = (tableId: string, targetTableId: string, result: TableAIEditState, baseBody: string, instruction: string) => {
    modal.setState('ready')
    modal.addMessage('assistant', '新表已生成。点击数据格可核对来源，确认后替换到正文。')
    body().replaceChildren(text(`要求：${instruction}`))
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
    const showSource = (label: string, column: string, source: { analysisId: string; factIds: string[]; selector: string | null } | undefined) => {
      detail.textContent = source
        ? `「${label} / ${column}」来源：${source.analysisId}${source.selector ? ` · ${source.selector}` : ''}${source.factIds.length ? ` · ${source.factIds.join('、')}` : ''}`
        : `「${label} / ${column}」未绑定来源（行标签或派生列，数值见登记事实）。`
    }
    const gridBody = document.createElement('tbody')
    for (const row of result.review?.rows ?? []) {
      const tr = document.createElement('tr')
      const th = document.createElement('th')
      th.setAttribute('scope', 'row'); th.append(text(row.label))
      tr.append(th)
      for (const cell of row.cells) {
        const td = document.createElement('td')
        td.className = `table-ai-cell-${cell.status}`
        const control = document.createElement('button')
        control.type = 'button'
        control.className = 'table-ai-cell'
        control.append(text(cell.text))
        control.setAttribute('aria-label', `${row.label} ${cell.column}：${cell.text}（${cell.status}，查看来源）`)
        control.addEventListener('click', () => showSource(row.label, cell.column, cell.source))
        td.append(control)
        tr.append(td)
      }
      gridBody.append(tr)
    }
    grid.append(gridBody)
    body().append(grid)
    detail.textContent = '点击数据格查看该格的来源事实。'
    body().append(detail)
    ;(result.warnings ?? []).forEach(warning => { const item = document.createElement('p'); item.setAttribute('role', 'alert'); item.append(text(warning)); body().append(item) })
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
      options.hooks?.onReplaced?.(result.editId); openedTableId = null
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
    actions.append(button('放弃', 'quiet', () => { openedTableId = null; modal.setState('idle'); modal.mountComposer(null); body().replaceChildren(text('已放弃本轮结果。继续编辑时，请在正文选择表格。')); modal.close() }))
    body().append(actions)
    modal.mountReviewActions(actions)
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
    const progress = document.createElement('div'); progress.className = 'ask-ai-progress'
    const stage = document.createElement('p'); stage.className = 'chart-ai-stage'; stage.setAttribute('role', 'status'); stage.textContent = '正在准备表格改动…'
    const elapsed = document.createElement('p'); elapsed.className = 'ask-ai-elapsed'; elapsed.textContent = '已用 0 秒'
    const startedAt = performance.now()
    const clock = progressClock = window.setInterval(() => { elapsed.textContent = `已用 ${Math.floor((performance.now() - startedAt) / 1000)} 秒` }, 1000)
    const hint = document.createElement('p'); hint.className = 'chart-ai-hint'; hint.textContent = '可收起侧栏继续阅读，任务在后台运行。'
    const cancel = button('取消改表', 'quiet', () => { invalidateCurrent(); void input(tableId, targetTableId, baseBody, previousEditId, '已取消本次改表。') })
    progress.append(stage, elapsed, hint, cancel); body().replaceChildren(progress)
    try {
      const expectedSha256 = await markdownSha256(baseBody)
      if (owner !== generation || disposed) return
      const payload = { baseBody, previousEditId, expectedSha256 }
      const started = templateId ? await options.client.startTableTemplateEdit(tableId, { ...payload, templateId }) : await options.client.startTableAiEdit(tableId, { ...payload, instruction })
      if (owner !== generation || disposed) { void options.client.cancelTableAiEdit(tableId, started.editId).catch(() => undefined); return }
      runningEditId = started.editId
      const result = await poll(tableId, started.editId, owner, stage)
      if (!result) return
      if (result.status === 'succeeded') review(tableId, targetTableId, result, baseBody, instruction)
      else await input(tableId, targetTableId, baseBody, previousEditId, result.error?.message ?? '改表未完成，原表保持不变。', result.status === 'failed')
    } catch {
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
      body().replaceChildren(text('正在读取表格信息…'))
      modal.mountComposer(null)
      modal.open()
      void options.client.tableEditRecordByTableId(targetTableId)
        .then(record => { if (!disposed && owner === generation) void input(targetTableId, targetTableId, latestBody, record.editId) })
        .catch(() => { if (!disposed && owner === generation) void input(targetTableId, targetTableId, latestBody) })
    },
    dispose() { disposed = true; invalidateCurrent(); modal.remove() },
  }
}
