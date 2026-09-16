import { describe, expect, it } from 'vitest'
import { reportPreflight, showPreflightPanel } from './preflight'

describe('reportPreflight', () => {
  it('returns soft warnings without blocking export', () => {
    const editor = document.createElement('div')
    editor.innerHTML = '<img src="chart.png">'
    expect(reportPreflight('###\n', editor).map((item) => item.code)).toEqual(['heading', 'empty-heading', 'image-alt'])
  })

  it('shows actionable warnings and keeps continue action available', () => {
    const root = document.createElement('main')
    document.body.append(root)
    const panel = showPreflightPanel(root, [{ code: 'heading', label: '尚未创建章节标题' }], () => {})
    expect(panel.querySelector('[data-preflight="continue"]')).not.toBeNull()
    expect(panel.textContent).toContain('尚未创建章节标题')
    panel.querySelector<HTMLButtonElement>('[data-preflight="close"]')!.click()
    expect(panel.isConnected).toBe(false)
  })
})
