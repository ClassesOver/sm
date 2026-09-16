import { describe, expect, it } from 'vitest'
import { reportPreflight, showPreflightPanel } from './preflight'

describe('reportPreflight', () => {
  it('returns soft warnings without blocking export', () => {
    const editor = document.createElement('div')
    editor.innerHTML = '<img src="chart.png">'
    expect(reportPreflight('###\n', editor).map((item) => item.code)).toEqual(['heading', 'empty-heading', 'image-alt'])
  })

  it('warns when an image alt contains only whitespace', () => {
    const editor = document.createElement('div')
    editor.innerHTML = '<img src="chart.png" alt="   ">'

    expect(reportPreflight('# 标题\n', editor).map((item) => item.code)).toContain('image-alt')
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

  it('returns to editing when Escape closes the preflight panel', () => {
    const root = document.createElement('main')
    document.body.append(root)
    let proceed: boolean | undefined
    const panel = showPreflightPanel(
      root,
      [{ code: 'heading', label: '尚未创建章节标题' }],
      (value) => { proceed = value },
    )

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(panel.isConnected).toBe(false)
    expect(proceed).toBe(false)
  })

  it('moves focus into the modal and restores the opener after closing', () => {
    const root = document.createElement('main')
    const opener = document.createElement('button')
    root.append(opener)
    document.body.append(root)
    opener.focus()
    const panel = showPreflightPanel(
      root,
      [{ code: 'heading', label: '尚未创建章节标题' }],
      () => {},
    )

    expect(document.activeElement).toBe(panel.querySelector('[data-preflight="close"]'))
    panel.querySelector<HTMLButtonElement>('[data-preflight="cancel"]')!.click()
    expect(document.activeElement).toBe(opener)
  })
})
