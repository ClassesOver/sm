import { beforeEach, expect, it, vi } from 'vitest'
import { createInteractiveCharts } from './interactive-charts'

const basePath = '/reports/v1/editor/report-1/1'
const charts = { 'reports/revision-1/chart.png': 'reports/revision-1/chart.plotly.json' }

beforeEach(() => {
  document.body.innerHTML = `<div id="editor"><img alt="收入趋势" src="${basePath}/asset/reports/revision-1/chart.png"></div>`
})

it('renders a registered chart while preserving the image node and accessible fallback', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar', x: [1], y: [2] }] }) })
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, {
    fetcher: fetcher as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })

  await controller.refresh()
  expect(fetcher).toHaveBeenCalledWith(`${basePath}/asset/reports/revision-1/chart.plotly.json`, expect.objectContaining({ credentials: 'same-origin' }))
  expect(plot.newPlot).toHaveBeenCalledOnce()
  expect(document.querySelectorAll('#editor img')).toHaveLength(1)
  expect(document.querySelector('#editor .interactive-chart')).toBeNull()
  expect(document.querySelector('#editor img')?.classList.contains('interactive-chart-fallback')).toBe(true)
  expect(document.querySelector('[role="img"]')?.getAttribute('aria-label')).toBe('收入趋势')
  controller.destroy()
  expect(plot.purge).toHaveBeenCalledOnce()
  expect(document.querySelector('#editor img')?.classList.contains('interactive-chart-fallback')).toBe(false)
})

it('keeps the image visible when loading or rendering fails', async () => {
  const fetcher = vi.fn().mockRejectedValue(new Error('offline'))
  const controller = createInteractiveCharts(document.querySelector('#editor')!, charts, basePath, { fetcher: fetcher as unknown as typeof fetch })
  await controller.refresh()
  expect(document.querySelector('#editor img')?.classList.contains('interactive-chart-fallback')).toBe(false)
  expect(document.querySelector('.interactive-chart')).toBeNull()
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
  await controller.refresh()
  expect(plot.newPlot).toHaveBeenCalledOnce()
  controller.destroy()
})

it('disposes stale instances when the editor replaces an image', async () => {
  const plot = { newPlot: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }
  const editor = document.querySelector<HTMLElement>('#editor')!
  const controller = createInteractiveCharts(editor, charts, basePath, {
    fetcher: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [{ type: 'bar' }] }) }) as unknown as typeof fetch,
    loadPlotly: async () => plot,
  })
  await controller.refresh()
  editor.innerHTML = '<p>新版正文</p>'
  await controller.refresh()
  expect(plot.purge).toHaveBeenCalledOnce()
  controller.destroy()
})
