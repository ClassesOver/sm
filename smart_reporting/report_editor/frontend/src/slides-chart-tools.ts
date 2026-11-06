import './slides-chart-tools.css'
import { askAIPanel } from './ask-ai-panel'
import { createAITaskAdapter, type TaskRequest } from './ai-task'
import type { ToolbarAction } from './toolbar'

type ChartTarget = { slideIndex: number; elementId: string; chartId: string; available: boolean; reason?: string }
type ChartProposal = { candidateId: string; previewDataUrl: string }
type Candidate = { id: string; target: ChartTarget }

export function createSlidesChartTools(host: HTMLElement, request: TaskRequest, changed: () => void,
  register?: (action: ToolbarAction) => () => void, locked: () => boolean = () => false) {
  const panel = document.createElement('section')
  panel.className = 'slides-chart-tools'; panel.setAttribute('aria-label', 'AI 改图')
  panel.innerHTML = '<label>图表 <select class="chart-target" aria-label="已登记数据图表"></select></label><p class="chart-status" role="status">正在读取已登记图表…</p><ul class="chart-pending" aria-label="待保存图表修改"></ul>'
  host.append(panel)
  const select = panel.querySelector<HTMLSelectElement>('select')!
  const status = panel.querySelector<HTMLElement>('.chart-status')!
  const pendingList = panel.querySelector<HTMLUListElement>('.chart-pending')!
  let charts: ChartTarget[] = []
  const pending = new Map<string, Candidate>()
  const key = (target: ChartTarget) => `${target.slideIndex}:${target.elementId}`
  const renderPending = () => {
    pendingList.replaceChildren()
    for (const [targetKey, item] of pending) {
      const row = document.createElement('li'); row.append(`第 ${item.target.slideIndex + 1} 页 · ${item.target.chartId} `)
      const undo = document.createElement('button'); undo.type = 'button'; undo.textContent = '撤销采纳'
      undo.addEventListener('click', () => { if (!locked()) { pending.delete(targetKey); renderPending(); changed() } })
      row.append(undo); pendingList.append(row)
    }
  }
  const open = () => {
    const target = charts[Number(select.value)]
    if (!target?.available || locked()) return
    let previous = pending.get(key(target))
    let applied: Candidate | undefined
    const session = askAIPanel().createTaskSession({
      kind: 'chart', label: `第 ${target.slideIndex + 1} 页 · ${target.chartId}`,
      captureInput: async () => ({ target: { slideIndex: target.slideIndex, elementId: target.elementId }, snapshot: { previousCandidateId: pending.get(key(target))?.id ?? null } }),
      adapter: createAITaskAdapter<ChartProposal>({
        kind: 'chart-edit', request,
        validateTarget: () => { if (locked()) throw new Error('幻灯片正在保存或已保存，请重新打开修订。') },
        renderProposal: (proposal, container) => {
          const image = document.createElement('img'); image.alt = '图表修改候选预览'; image.src = proposal.previewDataUrl
          container.replaceChildren(image)
        },
        applyProposal: async proposal => {
          previous = pending.get(key(target))
          applied = { id: proposal.candidateId, target }; pending.set(key(target), applied)
          renderPending(); changed()
        },
        undo: async () => {
          if (locked() || pending.get(key(target)) !== applied) throw new Error('此图表已有其他修改，无法直接撤销。')
          if (previous) pending.set(key(target), previous); else pending.delete(key(target))
          renderPending(); changed()
        },
      }),
    }); session.open()
  }
  if (register) register({ id: 'slides-chart-ai', bar: 'context', label: 'AI 改图', disabled: () => locked(), run: open })
  else {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = 'AI 改图'
    button.addEventListener('click', open); panel.prepend(button)
  }
  void request<{ charts: ChartTarget[] }>('charts').then(result => {
    charts = result.charts
    select.replaceChildren(...charts.map((chart, index) => {
      const option = document.createElement('option'); option.value = String(index)
      option.textContent = `第 ${chart.slideIndex + 1} 页 · ${chart.chartId}${chart.available ? '' : '（暂不可用）'}`
      option.disabled = !chart.available; return option
    }))
    select.value = String(charts.findIndex(chart => chart.available))
    status.textContent = charts.some(chart => chart.available) ? '图表候选采纳后可撤销，保存需单独操作。' : '当前没有可编辑的已登记图表。'
  }).catch(error => { status.textContent = error instanceof Error ? error.message : '图表编辑暂不可用。' })
  return {
    pendingEdits: () => [...pending.values()].map(item => ({ candidateId: item.id })),
    hasPending: (slideIndex: number, elementId: string) => pending.has(`${slideIndex}:${elementId}`),
    saved: () => { pending.clear(); renderPending() },
  }
}
