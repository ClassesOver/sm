import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createTemplatePanel } from './templates'

describe('report templates', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>'
  })

  it('requires confirmation before replacing a non-empty report', () => {
    const apply = vi.fn()
    vi.stubGlobal('confirm', () => false)
    const panel = createTemplatePanel(document.body, () => '# 现有报告\n', apply)
    panel.open()
    panel.dialog.querySelector<HTMLButtonElement>('[data-template="hospital-operations"]')!.click()
    expect(apply).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('applies the hospital operations template after confirmation', () => {
    const apply = vi.fn()
    vi.stubGlobal('confirm', () => true)
    const panel = createTemplatePanel(document.body, () => '# 现有报告\n', apply)
    panel.open()
    panel.dialog.querySelector<HTMLButtonElement>('[data-template="hospital-operations"]')!.click()
    expect(apply).toHaveBeenCalledWith(expect.stringContaining('# 医院整体运营情况分析报告'))
    expect(apply).toHaveBeenCalledWith(expect.stringContaining('## 核心结论'))
    vi.unstubAllGlobals()
  })

  it('appends a selected section block without replacing the report', () => {
    const apply = vi.fn()
    const panel = createTemplatePanel(document.body, () => '# 现有报告\n', apply)
    panel.open()
    panel.dialog.querySelector<HTMLButtonElement>('[data-template="risk-section"]')!.click()
    expect(apply).toHaveBeenCalledWith(expect.stringMatching(/^# 现有报告\n\n## 风险与建议/))
  })

  it('closes the template panel with Escape', () => {
    const panel = createTemplatePanel(document.body, () => '', vi.fn())
    panel.open()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(panel.dialog.hidden).toBe(true)
  })
})
