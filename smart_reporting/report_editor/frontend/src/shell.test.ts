import { beforeEach, describe, expect, it } from 'vitest'

import { createEditorShell } from './shell'

describe('createEditorShell', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>'
  })

  it('keeps editing, save, PDF, and Word actions available on desktop', () => {
    const root = document.querySelector<HTMLElement>('#app')!

    const shell = createEditorShell(root, 'full')

    expect(shell.editor.id).toBe('report-editor')
    expect(shell.outline.getAttribute('aria-label')).toBe('报告目录')
    const outlineClose = shell.outline.querySelector<HTMLButtonElement>('.outline-close')!
    expect(outlineClose.getAttribute('aria-label')).toBe('关闭目录')
    expect(outlineClose.title).toBe('关闭目录')
    expect(shell.outlineToggle.getAttribute('aria-controls')).toBe('report-outline')
    expect(shell.outlineToggle.getAttribute('aria-expanded')).toBe('true')
    expect(shell.viewToggle.getAttribute('aria-pressed')).toBe('true')
    expect(shell.retry.hidden).toBe(true)
    expect(shell.status.getAttribute('role')).toBe('status')
    expect(shell.status.getAttribute('aria-busy')).toBe('true')
    expect(shell.editor.getAttribute('aria-busy')).toBe('true')
    expect(shell.save.getAttribute('aria-label')).toBe('保存')
    expect(shell.search.getAttribute('aria-label')).toBe('搜索和替换')
    expect(shell.history.getAttribute('aria-label')).toBe('版本历史')
    expect(root.querySelector('[data-action="templates"]')).toBeNull()
    expect(root.querySelector('.toolbar-group-navigation')).not.toBeNull()
    expect(root.querySelector('.toolbar-group-output')).not.toBeNull()
    expect(root.querySelector('.outline-reorder-toggle')).toBeNull()
    expect(shell.more.getAttribute('aria-label')).toBe('更多操作')
    expect(shell.more.getAttribute('aria-controls')).toBe('report-secondary-actions')
    expect(shell.shortcuts.getAttribute('aria-label')).toBe('快捷键帮助')
    expect(shell.focus.getAttribute('aria-pressed')).toBe('false')
    expect(shell.focusExit.textContent).toBe('退出专注')
    expect(root.querySelector('.doc-metrics')?.textContent).toContain('0 字')
    expect(root.querySelector('.current-section')).not.toBeNull()
    expect(root.querySelector('.structure-status')).not.toBeNull()
    expect(root.querySelector<HTMLElement>('.network-status')?.hidden).toBe(true)
    expect(root.querySelector<HTMLElement>('.image-quality-status')?.hidden).toBe(true)
    expect(root.querySelector('.focus-hint')).toBeNull()
    expect(root.querySelector('.report-meta')?.querySelectorAll(':scope > span:not([hidden])')).toHaveLength(5)
    expect(root.querySelector('.report-meta')?.textContent).not.toContain('内容格式')
    expect(root.querySelector('.report-meta')?.textContent).not.toContain('自动保存已开启')
    expect(shell.exportPdf.getAttribute('aria-label')).toBe('导出 PDF')
    expect(shell.exportWord.getAttribute('aria-label')).toBe('导出 Word')
    expect(root.querySelector('.toolbar-shortcuts')).toBe(root.querySelector('.report-actions')?.lastElementChild)
    expect(root.classList.contains('toolbar-full')).toBe(true)
  })

  it('uses compact presentation without removing actions on mobile', () => {
    const root = document.querySelector<HTMLElement>('#app')!

    const shell = createEditorShell(root, 'compact')

    expect(root.classList.contains('toolbar-compact')).toBe(true)
    expect(shell.outlineToggle.getAttribute('aria-expanded')).toBe('false')
    expect(
      [shell.viewToggle, shell.save, shell.exportPdf, shell.exportWord].every(
        (item) => item.isConnected,
      ),
    ).toBe(true)
    expect(shell.search.isConnected).toBe(true)
    expect(shell.history.isConnected).toBe(true)
  })

  it('provides consistent icon affordances for toolbar actions', () => {
    const root = document.querySelector<HTMLElement>('#app')!

    createEditorShell(root, 'full')

    expect(
      Array.from(root.querySelectorAll<HTMLElement>('[data-lucide]')).map(
        (icon) => icon.dataset.lucide,
      ),
    ).toEqual([
      'panel-left',
      'maximize-2',
      'search',
      'history',
      'focus',
      'more-horizontal',
      'save',
      'file-down',
      'file-text',
      'settings-2',
      'keyboard',
      'x',
    ])
    expect(root.querySelector('[data-action="save"]')?.classList.contains('is-primary')).toBe(true)
  })
})
