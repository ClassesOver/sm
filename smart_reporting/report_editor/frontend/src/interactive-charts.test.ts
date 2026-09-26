import { beforeEach, expect, it, vi } from 'vitest'
import { createInteractiveCharts } from './interactive-charts'

const basePath = '/reports/v1/editor/report-1/1'
const charts = { 'reports/revision-1/chart.png': 'reports/revision-1/chart.plotly.json' }

function loadImages() {
  document.querySelectorAll<HTMLImageElement>('img').forEach((image) => {
    image.dispatchEvent(new Event('load'))
  })
}

beforeEach(() => {
  document.body.innerHTML = `<div id="editor"><img alt="收入趋势" src="${basePath}/asset/reports/revision-1/chart.png"></div>`
  document.querySelector<HTMLImageElement>('#editor img')!.getBoundingClientRect = () =>
    ({ left: 20, top: 40, width: 300, height: 180, right: 320, bottom: 220, x: 20, y: 40, toJSON: () => ({}) })
})

it('renders a registered chart as a body overlay without mutating the editor image', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar', x: [1], y: [2] }] }) })
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: fetcher as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })

  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  expect(fetcher).toHaveBeenCalledWith(`${basePath}/asset/reports/revision-1/chart.plotly.json`, expect.objectContaining({ credentials: 'same-origin' }))
  expect(plot.newPlot).toHaveBeenCalledOnce()
  expect(document.querySelectorAll('#editor img')).toHaveLength(1)
  // 覆盖层挂在 body 上，不进入编辑器 DOM，也绝不修改 img 本身（包括 class），
  // 避免 ProseMirror 把外部变更当作文档修改或按模型重绘形成渲染循环。
  expect(document.querySelector('#editor .interactive-chart')).toBeNull()
  expect(document.querySelector('#editor img')?.classList.length).toBe(0)
  expect(document.querySelector('#editor img')?.getAttribute('style')).toBeNull()
  const overlay = document.body.querySelector('.interactive-chart')
  expect(overlay).not.toBeNull()
  expect(overlay?.getAttribute('aria-label')).toBe('收入趋势')
  expect(overlay?.getAttribute('role')).toBe('img')
  controller.destroy()
  expect(plot.purge).toHaveBeenCalledOnce()
  expect(document.body.querySelector('.interactive-chart')).toBeNull()
  expect(document.querySelector('#editor img')?.classList.length).toBe(0)
})

it('leaves the image untouched when loading or rendering fails', async () => {
  const fetcher = vi.fn().mockRejectedValue(new Error('offline'))
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, { fetcher: fetcher as unknown as typeof fetch })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  expect(document.querySelector('#editor img')?.classList.length).toBe(0)
  expect(document.querySelector('.interactive-chart')).toBeNull()
  controller.destroy()
})

it('repositions an active chart when preceding editor content changes', async () => {
  const editor = document.querySelector<HTMLElement>('#editor')!
  const image = editor.querySelector('img')!
  let top = 40
  image.getBoundingClientRect = () => ({ left: 20, top, width: 300, height: 180, right: 320, bottom: top + 180, x: 20, y: top, toJSON: () => ({}) })
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const controller = createInteractiveCharts(editor, charts, basePath, {
    fetcher: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar' }] }) }) as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  const overlay = document.querySelector<HTMLElement>('.interactive-chart')!
  expect(overlay.style.top).toBe('40px')

  top = 120
  editor.prepend(document.createElement('p'))
  await vi.waitFor(() => expect(overlay.style.top).toBe('120px'))
  expect(plot.newPlot).toHaveBeenCalledOnce()
  controller.destroy()
})

it('matches the relative image reference emitted by the Markdown renderer', async () => {
  const image = document.querySelector<HTMLImageElement>('#editor img')!
  image.src = `${basePath}/asset/chart.png`
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar' }] }) }) as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  expect(plot.newPlot).toHaveBeenCalledOnce()
  controller.destroy()
})

it('opens an expanded modal with the same figure and closes it cleanly', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const figure = { data: [{ type: 'bar', x: [1], y: [2] }], layout: { title: { text: '趋势' } }, config: {} }
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => figure })
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: fetcher as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  expect(plot.newPlot).toHaveBeenCalledOnce()

  const expand = document.querySelector<HTMLButtonElement>('.interactive-chart-expand')!
  expect(expand).not.toBeNull()
  expand.click()
  const modal = document.body.querySelector('.interactive-chart-modal')
  expect(modal).not.toBeNull()
  expect(modal?.getAttribute('role')).toBe('dialog')
  expect(document.body.querySelector('.interactive-chart-modal-canvas')).not.toBeNull()
  // 原图 + 模态大图各渲染一次，模态复用同一份 figure 数据
  expect(plot.newPlot).toHaveBeenCalledTimes(2)
  expect(plot.newPlot.mock.calls[1][1]).toBe(figure.data)

  document.body.querySelector<HTMLButtonElement>('.interactive-chart-modal-close')!.click()
  expect(document.body.querySelector('.interactive-chart-modal')).toBeNull()
  expect(plot.purge).toHaveBeenCalledOnce()
  controller.destroy()
})

it('opens the expanded modal via keyboard on the chart', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar' }] }) })
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: fetcher as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  const overlay = document.body.querySelector<HTMLElement>('.interactive-chart')!
  expect(overlay.tabIndex).toBe(0)
  overlay.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  expect(document.body.querySelector('.interactive-chart-modal')).not.toBeNull()
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(document.body.querySelector('.interactive-chart-modal')).toBeNull()
  controller.destroy()
})

it('disposes stale instances when the editor replaces an image', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const editor = document.querySelector<HTMLElement>('#editor')!
  const controller = createInteractiveCharts(editor, charts, basePath, {
    fetcher: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar' }] }) }) as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise
  editor.innerHTML = '<p>新版正文</p>'
  await controller.refresh()
  expect(plot.purge).toHaveBeenCalledOnce()
  controller.destroy()
})

it('normalizes title-legend and same-side axis overlaps before rendering', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const figure = {
    data: [{ type: 'scatter', yaxis: 'y3' }],
    layout: {
      title: { text: '2025年月度单位工作量成本走势' },
      legend: { orientation: 'h', y: 1.06, x: 0.5, xanchor: 'center', yanchor: 'bottom' },
      yaxis: { title: { text: '门诊单位成本（元）' } },
      yaxis2: { title: { text: '床日单位成本（元）' }, overlaying: 'y', side: 'right' },
      yaxis3: { title: { text: '住院单位成本（元）' }, overlaying: 'y', side: 'left', showgrid: false },
    },
  }
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: vi.fn().mockResolvedValue({ ok: true, json: async () => figure }) as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise

  const layout = plot.newPlot.mock.calls[0][2] as Record<string, any>
  // 顶部水平图例移到绘图区下方，不再压标题
  expect(layout.legend).toMatchObject({ orientation: 'h', y: -0.22, yanchor: 'top', x: 0.5, xanchor: 'center' })
  expect(layout.margin.b).toBeGreaterThanOrEqual(110)
  // 与主轴同侧的第二条 overlaying 轴外置到空余纸面，不再刻度重叠
  expect(layout.yaxis2.anchor).toBeUndefined()
  expect(layout.yaxis3).toMatchObject({ anchor: 'free', position: 0 })
  expect(layout.xaxis.domain).toEqual([0.08, 1])
  // 原始 figure 不被修改
  expect(figure.layout.legend.y).toBe(1.06)
  expect((figure.layout.yaxis3 as Record<string, unknown>).anchor).toBeUndefined()
  controller.destroy()
})

it('leaves non-colliding legend and axes untouched', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const figure = {
    data: [{ type: 'bar' }],
    layout: {
      title: { text: '趋势' },
      legend: { orientation: 'h', y: -0.2, yanchor: 'top' },
      yaxis2: { overlaying: 'y', side: 'right' },
    },
  }
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: vi.fn().mockResolvedValue({ ok: true, json: async () => figure }) as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  const refreshPromise = controller.refresh()
  loadImages()
  await refreshPromise

  const layout = plot.newPlot.mock.calls[0][2] as Record<string, any>
  expect(layout.legend.y).toBe(-0.2)
  expect(layout.yaxis2.autoshift).toBeUndefined()
  controller.destroy()
})
