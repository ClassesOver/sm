import { describe, expect, it, vi } from 'vitest'

import { createSlidesChartTools } from './slides-chart-tools'

describe('PPTX registered chart editing', () => {
  it('keeps candidates out of save payload until adoption and supports undo', async () => {
    const host = document.createElement('aside')
    const request = vi.fn().mockResolvedValueOnce({ charts: [
      { slideIndex: 1, elementId: 'picture-1', chartId: 'chart_001', available: true },
    ] }).mockResolvedValueOnce({ candidateId: 'chart-edit-1' })
      .mockResolvedValueOnce({ candidateId: 'chart-edit-1', status: 'succeeded', previewDataUrl: 'data:image/png;base64,cG5n' })
    const tools = createSlidesChartTools(host, request, () => {})
    await vi.waitFor(() => expect(host.querySelectorAll('option')).toHaveLength(1))
    host.querySelector<HTMLTextAreaElement>('textarea')!.value = '改为横向条形图'
    host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.chart-preview')!.hidden).toBe(false))
    expect(tools.pendingEdits()).toEqual([])
    expect(host.querySelector('img')!.src).toBe('data:image/png;base64,cG5n')
    expect(request).toHaveBeenCalledWith('charts/chart-edit-1?wait_ms=1500')
    host.querySelector<HTMLButtonElement>('.chart-accept')!.click()
    expect(tools.pendingEdits()).toEqual([{ candidateId: 'chart-edit-1' }])
    expect(host.querySelector('.chart-pending')!.textContent).toContain('chart_001')
    host.querySelector<HTMLButtonElement>('.chart-pending button')!.click()
    expect(tools.pendingEdits()).toEqual([])
    expect(host.querySelector('.chart-pending')!.children).toHaveLength(0)
  })

  it('retains the existing accepted candidate when subsequent generation fails', async () => {
    const host = document.createElement('aside')
    const request = vi.fn().mockResolvedValueOnce({ charts: [
      { slideIndex: 0, elementId: 'picture-1', chartId: 'chart_001', available: true },
    ] }).mockResolvedValueOnce({ candidateId: 'chart-edit-1' })
      .mockResolvedValueOnce({ status: 'succeeded', previewDataUrl: 'data:image/png;base64,cG5n' })
      .mockRejectedValueOnce(new Error('Matplotlib 绘图失败'))
    const tools = createSlidesChartTools(host, request, () => {})
    await vi.waitFor(() => expect(host.querySelectorAll('option')).toHaveLength(1))
    host.querySelector<HTMLTextAreaElement>('textarea')!.value = '调整颜色'
    const form = host.querySelector('form')!
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.chart-preview')!.hidden).toBe(false))
    host.querySelector<HTMLButtonElement>('.chart-accept')!.click()
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(host.querySelector('.chart-status')!.textContent).toBe('Matplotlib 绘图失败'))
    expect(tools.pendingEdits()).toEqual([{ candidateId: 'chart-edit-1' }])
    expect(host.querySelector<HTMLElement>('.chart-preview')!.hidden).toBe(true)
  })
})
