import type { EditorView } from '@milkdown/kit/prose/view'
import { TABLE_PROTOCOL_EDIT_META } from './protocol-plugin'
import { buttonClasses } from './button'
import { createModal } from './modal'
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
  pollIntervalMs?: number
  hooks?: { onReplaced?: (editId: string) => void; onError?: (code: string) => void }
}): TableAIEditController {
  const interval = options.pollIntervalMs ?? 800
  let disposed = false
  const modal = createModal({ root: document.body, overlayClass: 'table-ai-edit', cardClass: 'table-ai-edit-card', closeClass: 'table-ai-edit-close', closeLabel: '关闭 AI 改表', labelledBy: 'table-ai-title', variant: 'wide', content: '<div class="panel-header"><h2 id="table-ai-title">AI 改表</h2></div><div data-role="body"></div>' })
  const body = () => modal.card.querySelector<HTMLElement>('[data-role="body"]')!
  const poll = async (tableId: string, editId: string): Promise<TableAIEditState> => {
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, interval))
      const state = await options.client.tableAiEditStatus(tableId, editId)
      if (state.status === 'succeeded' || state.status === 'failed' || state.status === 'cancelled') return state
    }
  }
  const input = async (tableId: string, targetTableId: string, baseBody: string, previousEditId?: string, note = '') => {
    body().replaceChildren(text(note))
    const area = document.createElement('textarea')
    area.id = 'table-ai-input'; area.maxLength = 2000; area.rows = 3
    area.placeholder = '例如：按同比增幅从高到低排列并标注低于100%的项目'
    body().append(text('改表要求'), area)
    const templateRoot = document.createElement('div'); templateRoot.className = 'table-ai-templates'; body().append(templateRoot)
    const templates = await options.client.tableTemplates(tableId).catch(() => ({ templates: [] as EditorTemplateInfo[] }))
    templates.templates.forEach(item => {
      const node = button(item.name, 'secondary', () => void runTemplate(tableId, targetTableId, item.templateId, baseBody, previousEditId), 'table-ai-template')
      node.disabled = !item.available; node.title = item.reason ?? ''; templateRoot.append(node)
    })
    body().append(button('生成改表', 'primary', () => { const instruction = area.value.trim(); if (instruction) void runEdit(tableId, targetTableId, instruction, baseBody, previousEditId) }))
    if (!disposed) modal.open(area)
  }
  const review = (tableId: string, targetTableId: string, result: TableAIEditState, baseBody: string, instruction: string) => {
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
    body().append(button('接受替换', 'primary', () => { if (!result.markdown || !replaceTableProtocolBlock(options.view, targetTableId, result.markdown, result.baseCaption)) { options.hooks?.onError?.('report_editor_table_ai_target_missing'); return }; options.hooks?.onReplaced?.(result.editId); modal.close() }))
    body().append(button('继续调整', 'secondary', () => void input(tableId, targetTableId, baseBody, result.editId, '已基于上一轮结果继续调整。')))
    body().append(button('放弃', 'quiet', () => modal.close()))
  }
  const runEdit = async (tableId: string, targetTableId: string, instruction: string, baseBody: string, previousEditId?: string) => { body().replaceChildren(text('正在准备表格改动…')); try { const expectedSha256 = await markdownSha256(baseBody); const started = await options.client.startTableAiEdit(tableId, { instruction, baseBody, previousEditId, expectedSha256 }); const result = await poll(tableId, started.editId); if (result.status === 'succeeded') review(tableId, targetTableId, result, baseBody, instruction); else await input(tableId, targetTableId, baseBody, previousEditId, result.error?.message ?? '改表未完成，原表保持不变。') } catch { await input(tableId, targetTableId, baseBody, previousEditId, '改表请求失败，原表保持不变。') } }
  const runTemplate = async (tableId: string, targetTableId: string, templateId: string, baseBody: string, previousEditId?: string) => { body().replaceChildren(text('正在套用预制模板…')); try { const expectedSha256 = await markdownSha256(baseBody); const started = await options.client.startTableTemplateEdit(tableId, { templateId, baseBody, previousEditId, expectedSha256 }); const result = await poll(tableId, started.editId); if (result.status === 'succeeded') review(tableId, targetTableId, result, baseBody, `套用模板：${templateId}`); else await input(tableId, targetTableId, baseBody, previousEditId, result.error?.message ?? '模板未完成，原表保持不变。') } catch { await input(tableId, targetTableId, baseBody, previousEditId, '模板请求失败，原表保持不变。') } }
  return {
    open(targetTableId, baseBody = '') {
      void options.client.tableEditRecordByTableId(targetTableId)
        .then(record => input(targetTableId, targetTableId, baseBody, record.editId))
        .catch(() => input(targetTableId, targetTableId, baseBody))
    },
    dispose() { disposed = true; modal.remove() },
  }
}
