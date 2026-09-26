import { describe, expect, it } from 'vitest'
import { formalHeadings, reportPreflight, showPreflightPanel } from './preflight'

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

describe('formal heading preflight', () => {
  const original = '# 报告\n\n[[section:income]]\n\n## 1. 收入\n\n### 1.1 明细\n\n正文\n\n```\n## 代码里的井号\n```\n\n## 2. 成本\n'

  it('ignores body edits and fenced code', () => {
    const editor = document.createElement('div')
    const edited = original.replace('正文', '改写后的正文')
    expect(reportPreflight(edited, editor, formalHeadings(original)).map((item) => item.code)).not.toContain('formal-headings')
    expect(formalHeadings(original)).toEqual(['2|1. 收入', '3|1.1 明细', '2|2. 成本'])
  })

  it('warns when a formal heading is renamed or reordered', () => {
    const editor = document.createElement('div')
    const expected = formalHeadings(original)
    const renamed = original.replace('## 2. 成本', '## 2. 成本分析')
    const reordered = original.replace('## 1. 收入', '## 2. 成本').replace(/## 2\. 成本\n$/, '## 1. 收入\n')
    for (const markdown of [renamed, reordered]) {
      expect(reportPreflight(markdown, editor, expected).map((item) => item.code)).toContain('formal-headings')
    }
  })
})
