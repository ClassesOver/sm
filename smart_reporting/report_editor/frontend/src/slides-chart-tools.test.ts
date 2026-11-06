import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSlidesChartTools } from './slides-chart-tools'
afterEach(() => document.body.replaceChildren())
describe('PPTX registered chart editing', () => {
  async function setup() {
    const host = document.createElement('aside'); document.body.append(host)
    const request = vi.fn().mockResolvedValueOnce({ charts: [{ slideIndex: 1, elementId: 'picture-1', chartId: 'chart_001', available: true }] })
      .mockResolvedValueOnce({ taskId: 'task-1' })
      .mockResolvedValueOnce({ taskId: 'task-1', state: 'ready', kind: 'chart-edit', proposal: { candidateId: 'native-chart-1', previewDataUrl: 'data:image/png;base64,cG5n' } })
      .mockResolvedValueOnce({ state: 'accepted' })
    const tools = createSlidesChartTools(host, request, () => {})
    await vi.waitFor(() => expect(host.querySelectorAll('option')).toHaveLength(1))
    host.querySelector('button')!.click()
    document.querySelector<HTMLTextAreaElement>('.ask-ai-composers textarea')!.value = '调整颜色'
    document.querySelector('.ask-ai-composers form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(document.querySelector('[data-task-action="accept"]')).not.toBeNull())
    return { host, tools, request }
  }
  it('uses shared session and keeps native candidate ID out of save payload until adoption', async () => {
    const { tools, host, request } = await setup()
    expect(tools.pendingEdits()).toEqual([])
    expect(document.querySelector('.ai-task-preview img')?.getAttribute('src')).toBe('data:image/png;base64,cG5n')
    expect(request).toHaveBeenCalledWith('ai/tasks/task-1')
    document.querySelector<HTMLButtonElement>('[data-task-action="accept"]')!.click()
    await vi.waitFor(() => expect(tools.pendingEdits()).toEqual([{ candidateId: 'native-chart-1' }]))
    host.querySelector<HTMLButtonElement>('.chart-pending button')!.click(); expect(tools.pendingEdits()).toEqual([])
  })
  it('retains an accepted candidate when subsequent generation fails', async () => {
    const { tools, host, request } = await setup()
    document.querySelector<HTMLButtonElement>('[data-task-action="accept"]')!.click()
    await vi.waitFor(() => expect(tools.pendingEdits()).toHaveLength(1))
    request.mockRejectedValueOnce(new Error('Matplotlib 绘图失败'))
    host.querySelector('button')!.click()
    const forms = document.querySelectorAll<HTMLFormElement>('.ask-ai-composers form')
    forms[forms.length - 1]!.querySelector('textarea')!.value = '再调整'
    forms[forms.length - 1]!.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(document.querySelector('.ask-ai-panel')!.textContent).toContain('Matplotlib 绘图失败'))
    expect(tools.pendingEdits()).toEqual([{ candidateId: 'native-chart-1' }])
  })
})

it('undoes the latest chart adoption in the same session to the previous candidate', async () => {
  const host = document.createElement('aside'); document.body.append(host)
  let round = 0
  const request = vi.fn().mockImplementation(async (path: string) => {
    if (path === 'charts') return { charts: [{ slideIndex: 0, elementId: 'chart', chartId: 'chart_1', available: true }] }
    if (path === 'ai/tasks') return { taskId: `task-${++round}` }
    if (/ai\/tasks\/task-\d$/.test(path)) return { taskId: `task-${round}`, state: 'ready', kind: 'chart-edit', proposal: { candidateId: `candidate-${round}`, previewDataUrl: 'data:image/png;base64,cG5n' } }
    return {}
  })
  const tools = createSlidesChartTools(host, request, () => {})
  await vi.waitFor(() => expect(host.querySelector('option')).not.toBeNull())
  host.querySelector('button')!.click()
  const form = document.querySelector<HTMLFormElement>('.ask-ai-composers form')!
  for (const index of [1, 2]) {
    form.querySelector('textarea')!.value = `修改 ${index}`
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(document.querySelector<HTMLButtonElement>('[data-task-action="accept"]')?.hidden).toBe(false))
    document.querySelector<HTMLButtonElement>('[data-task-action="accept"]')!.click()
    await vi.waitFor(() => expect(tools.pendingEdits()).toEqual([{ candidateId: `candidate-${index}` }]))
  }
  document.querySelector<HTMLButtonElement>('[data-task-action="undo"]')!.click()
  await vi.waitFor(() => expect(tools.pendingEdits()).toEqual([{ candidateId: 'candidate-1' }]))
})
