import './slides-chart-tools.css'

type ChartTarget = { slideIndex: number; elementId: string; chartId: string; available: boolean; reason?: string }
type ChartStatus = { candidateId: string; status: string; previewDataUrl?: string; error?: { message?: string } }
type Request = <T>(path: string, init?: RequestInit) => Promise<T>

export function createSlidesChartTools(host: HTMLElement, request: Request, changed: () => void) {
  const panel = document.createElement('section')
  panel.className = 'slides-chart-tools'
  panel.setAttribute('aria-label', 'AI 改图')
  panel.innerHTML = `
    <form class="chart-form"><label>AI 改图 <select class="chart-target" aria-label="已登记数据图表"></select></label>
    <textarea class="chart-instruction" rows="2" maxlength="2000" aria-label="图表调整要求" placeholder="描述颜色、标签或图形调整；沿用已登记数据"></textarea>
    <button class="chart-generate" type="submit">生成候选</button><button class="chart-cancel" type="button" hidden>取消</button></form>
    <p class="chart-status" role="status">正在读取已登记图表…</p>
    <div class="chart-preview" hidden><img alt="图表修改候选预览"><button class="chart-accept" type="button">采纳候选</button></div>
    <ul class="chart-pending" aria-label="待保存图表修改"></ul>`
  host.append(panel)
  const select = panel.querySelector<HTMLSelectElement>('.chart-target')!
  const instruction = panel.querySelector<HTMLTextAreaElement>('.chart-instruction')!
  const generate = panel.querySelector<HTMLButtonElement>('.chart-generate')!
  const cancel = panel.querySelector<HTMLButtonElement>('.chart-cancel')!
  const accept = panel.querySelector<HTMLButtonElement>('.chart-accept')!
  const status = panel.querySelector<HTMLElement>('.chart-status')!
  const preview = panel.querySelector<HTMLElement>('.chart-preview')!
  const image = preview.querySelector('img')!
  const pendingList = panel.querySelector<HTMLUListElement>('.chart-pending')!
  let charts: ChartTarget[] = []
  let active = ''
  let candidate: { id: string; target: ChartTarget } | undefined
  const pending = new Map<string, { id: string; target: ChartTarget }>()
  const key = (target: ChartTarget) => `${target.slideIndex}:${target.elementId}`
  const renderPending = () => {
    pendingList.replaceChildren()
    for (const [targetKey, item] of pending) {
      const row = document.createElement('li')
      row.append(`第 ${item.target.slideIndex + 1} 页 · ${item.target.chartId} `)
      const undo = document.createElement('button')
      undo.type = 'button'
      undo.textContent = '撤销采纳'
      undo.addEventListener('click', () => { pending.delete(targetKey); renderPending(); changed() })
      row.append(undo)
      pendingList.append(row)
    }
  }
  panel.querySelector('form')!.addEventListener('submit', async event => {
    event.preventDefault()
    const target = charts[Number(select.value)]
    if (!target || !target.available || !instruction.value.trim() || generate.disabled) return
    generate.disabled = true
    preview.hidden = true
    candidate = undefined
    status.textContent = '正在生成图表候选…'
    try {
      const started = await request<{ candidateId: string }>('charts/start', {
        method: 'POST', body: JSON.stringify({ slideIndex: target.slideIndex, elementId: target.elementId, instruction: instruction.value }),
      })
      active = started.candidateId
      cancel.hidden = false
      let result: ChartStatus
      do {
        result = await request<ChartStatus>(`charts/${encodeURIComponent(active)}?wait_ms=1500`)
      } while (result.status === 'running' || result.status === 'pending' || result.status === 'queued')
      if (result.status === 'succeeded' && result.previewDataUrl) {
        candidate = { id: active, target }
        image.src = result.previewDataUrl
        preview.hidden = false
        status.textContent = '候选已就绪，采纳后保存为新修订。'
      } else status.textContent = result.error?.message ?? '未生成可采纳图表，原图保持不变。'
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : '生成失败，原图保持不变。'
    } finally { active = ''; cancel.hidden = true; generate.disabled = false }
  })
  cancel.addEventListener('click', async () => {
    if (!active) return
    cancel.disabled = true
    try { await request(`charts/${encodeURIComponent(active)}/cancel`, { method: 'POST' }) }
    catch (error) { status.textContent = error instanceof Error ? error.message : '取消失败' }
    finally { cancel.disabled = false }
  })
  accept.addEventListener('click', () => {
    if (!candidate) return
    pending.set(key(candidate.target), candidate)
    candidate = undefined
    preview.hidden = true
    renderPending()
    changed()
    status.textContent = '图表候选已采纳，可撤销或保存。'
  })
  const load = async () => {
    try {
      charts = (await request<{ charts: ChartTarget[] }>('charts')).charts
      select.replaceChildren(...charts.map((chart, index) => {
        const option = document.createElement('option')
        option.value = String(index)
        option.textContent = `第 ${chart.slideIndex + 1} 页 · ${chart.chartId}${chart.available ? '' : '（暂不可用）'}`
        option.disabled = !chart.available
        return option
      }))
      const first = charts.findIndex(chart => chart.available)
      select.value = String(first)
      generate.disabled = first < 0
      status.textContent = first >= 0 ? '仅调整已有登记数据图表，先预览后采纳。' : '当前没有可编辑的已登记图表。'
    } catch (error) {
      generate.disabled = true
      status.textContent = error instanceof Error ? error.message : '图表编辑暂不可用。'
    }
  }
  void load()
  return {
    pendingEdits: () => [...pending.values()].map(item => ({ candidateId: item.id })),
    hasPending: (slideIndex: number, elementId: string) => pending.has(`${slideIndex}:${elementId}`),
    saved: () => { pending.clear(); renderPending() },
  }
}
