import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createMoreActionsController,
  createNetworkStatusController,
  createFocusModeController,
  createExportPanel,
  createImagePreview,
  createEditorPreferenceController,
  installEditorShortcuts,
} from './enhancements'
import { createShortcutsPanel } from './shortcuts'

describe('report editor enhancements', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <main id="app" class="report-app view-a4"></main>
      <button id="view" aria-pressed="true"></button>
      <div id="editor"><img src="chart.png" alt="收入趋势"></div>
    `
  })

  it('exposes a plain-language save-state description', () => {
    const status = document.createElement('div')
    status.className = 'save-state'
    const label = document.createElement('span')
    label.className = 'save-state-label'
    status.append(label)
    document.body.append(status)
    status.dataset.state = 'dirty'
    label.textContent = '有未保存修改'
    status.setAttribute('title', '修改会自动保存，也可以使用保存按钮立即保存')
    expect(status.title).toContain('自动保存')
  })

  it('persists view and outline preferences by report key', () => {
    localStorage.clear()
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.querySelector<HTMLButtonElement>('#view')!
    const controller = createEditorPreferenceController(root, toggle, 'report-1')
    controller.setOutlineCollapsed(true)
    toggle.click()
    expect(localStorage.getItem('smart-reporting-editor:prefs:report-1')).toContain('"view":"a4"')
    const secondRoot = document.createElement('main')
    const secondToggle = document.createElement('button')
    secondRoot.append(secondToggle)
    createEditorPreferenceController(secondRoot, secondToggle, 'report-1')
    expect(secondRoot.classList).toContain('view-a4')
    expect(secondRoot.classList).toContain('outline-collapsed')
  })

  it('ignores invalid persisted preference values', () => {
    localStorage.clear()
    localStorage.setItem(
      'smart-reporting-editor:prefs:invalid-prefs',
      JSON.stringify({ view: 'broken', outlineCollapsed: 'yes' }),
    )
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.querySelector<HTMLButtonElement>('#view')!

    createEditorPreferenceController(root, toggle, 'invalid-prefs')

    expect(root.classList).toContain('view-wide')
    expect(root.classList).not.toContain('outline-collapsed')
  })

  it('applies default preferences without redundant storage writes', () => {
    localStorage.clear()
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.querySelector<HTMLButtonElement>('#view')!
    try {
      createEditorPreferenceController(root, toggle, 'report-defaults')

      expect(setItem).not.toHaveBeenCalled()
    } finally {
      setItem.mockRestore()
    }
  })

  it('keeps preferences usable when localStorage writes fail', () => {
    localStorage.clear()
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota exceeded', 'QuotaExceededError')
    })
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.querySelector<HTMLButtonElement>('#view')!

    try {
      const controller = createEditorPreferenceController(root, toggle, 'report-quota')
      expect(() => controller.setOutlineCollapsed(true)).not.toThrow()
      expect(() => controller.saveScroll(240)).not.toThrow()
      expect(root.classList).toContain('outline-collapsed')
    } finally {
      setItem.mockRestore()
    }
  })

  it('restores the saved scroll position after editor loading', () => {
    localStorage.clear()
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.querySelector<HTMLButtonElement>('#view')!
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    const controller = createEditorPreferenceController(root, toggle, 'report-scroll')
    controller.saveScroll(640)
    controller.restoreScroll()
    expect(scrollTo).toHaveBeenCalledWith({ top: 640, behavior: 'auto' })
    vi.unstubAllGlobals()
  })

  it('maps save and export keyboard shortcuts', () => {
    const save = vi.fn()
    const exportPdf = vi.fn()
    installEditorShortcuts({ save, exportPdf })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true }))
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'e', ctrlKey: true, shiftKey: true }),
    )

    expect(save).toHaveBeenCalledOnce()
    expect(exportPdf).toHaveBeenCalledOnce()
  })

  it('closes mobile secondary actions after selection, outside click, or Escape', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    root.innerHTML = `<button id="more" aria-expanded="false"></button><div class="secondary-actions"><button id="search"></button></div>`
    const more = document.querySelector<HTMLButtonElement>('#more')!
    createMoreActionsController(root, more)

    more.click()
    expect(root.classList).toContain('more-actions-open')
    document.querySelector<HTMLButtonElement>('#search')!.click()
    expect(root.classList).not.toContain('more-actions-open')

    more.click()
    document.body.click()
    expect(root.classList).not.toContain('more-actions-open')

    more.click()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(more.getAttribute('aria-expanded')).toBe('false')
  })

  it('moves focus into mobile actions and restores it when Escape closes them', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    root.innerHTML = `<button id="more" aria-expanded="false">更多</button><div class="secondary-actions"><button id="search">搜索</button><button>历史</button></div>`
    const more = document.querySelector<HTMLButtonElement>('#more')!
    const search = document.querySelector<HTMLButtonElement>('#search')!
    createMoreActionsController(root, more)

    more.click()
    expect(document.activeElement).toBe(search)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(document.activeElement).toBe(more)
  })

  it('does not steal focus back after choosing a mobile action', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    root.innerHTML = `<button id="more" aria-expanded="false">更多</button><div class="secondary-actions"><button id="search">搜索</button></div>`
    const more = document.querySelector<HTMLButtonElement>('#more')!
    const search = document.querySelector<HTMLButtonElement>('#search')!
    createMoreActionsController(root, more)

    more.click()
    search.focus()
    search.click()

    expect(root.classList).not.toContain('more-actions-open')
    expect(document.activeElement).toBe(search)
  })

  it('opens and closes a static image preview', () => {
    const preview = createImagePreview(document.querySelector<HTMLElement>('#editor')!)
    document.querySelector<HTMLImageElement>('#editor img')!.click()

    expect(preview.dialog.hidden).toBe(false)
    expect(preview.dialog.querySelector('img')?.getAttribute('src')).toBe('chart.png')
    expect(document.activeElement).toBe(preview.dialog.querySelector('.image-preview-close'))
    expect(preview.dialog.getAttribute('role')).toBe('dialog')
    expect(preview.dialog.getAttribute('aria-modal')).toBe('true')
    expect(preview.dialog.getAttribute('aria-label')).toBe('图片预览')
    expect(preview.close.title).toBe('关闭图片预览')

    preview.close.click()
    expect(preview.dialog.hidden).toBe(true)
  })

  it('opens image previews from the keyboard and restores image focus', () => {
    const source = document.querySelector<HTMLImageElement>('#editor img')!
    const preview = createImagePreview(document.querySelector<HTMLElement>('#editor')!)

    expect(source.tabIndex).toBe(0)
    source.focus()
    source.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))

    expect(preview.dialog.hidden).toBe(false)
    preview.close.click()
    expect(document.activeElement).toBe(source)
  })

  it('prepares newly rendered images while excluding interactive chart fallbacks', async () => {
    const editor = document.querySelector<HTMLElement>('#editor')!
    const fallback = document.createElement('img')
    fallback.className = 'interactive-chart-fallback'
    editor.append(fallback)
    const preview = createImagePreview(editor)
    const added = document.createElement('img')
    added.src = 'new-chart.png'
    added.alt = '新增趋势'
    editor.append(added)

    await vi.waitFor(() => expect(added.tabIndex).toBe(0))
    expect(fallback.tabIndex).toBe(-1)
    added.focus()
    added.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))

    expect(preview.dialog.hidden).toBe(false)
    expect(preview.dialog.querySelector('img')?.getAttribute('src')).toBe('new-chart.png')
  })

  it('enters focus mode with a shortcut and exits with Escape', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    const editor = document.createElement('textarea')
    root.append(editor)
    createFocusModeController(root)
    editor.focus()

    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, shiftKey: true }),
    )
    expect(root.classList).toContain('focus-mode')
    expect(document.activeElement).toBe(editor)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(root.classList).not.toContain('focus-mode')
  })

  it('toggles focus mode from visible controls', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.createElement('button')
    toggle.innerHTML = '<span>专注</span>'
    const exit = document.createElement('button')
    root.append(toggle, exit)
    createFocusModeController(root, toggle, exit)
    toggle.focus()
    toggle.click()
    expect(root.classList).toContain('focus-mode')
    expect(document.activeElement).toBe(exit)
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    expect(toggle.getAttribute('aria-label')).toBe('退出专注模式')
    expect(toggle.title).toBe('退出专注模式')
    expect(toggle.querySelector('span')?.textContent).toBe('退出专注')
    expect(exit.title).toBe('退出专注模式')
    exit.click()
    expect(root.classList).not.toContain('focus-mode')
    expect(document.activeElement).toBe(toggle)
    expect(toggle.getAttribute('aria-label')).toBe('进入专注模式')
    expect(toggle.title).toBe('专注模式')
    expect(toggle.querySelector('span')?.textContent).toBe('专注')
  })

  it('shows export links without navigating away', () => {
    const panel = createExportPanel()
    panel.show({
      revision: 2,
      requestId: '01995f3d-7bd2-7000-8000-000000000001',
      pdf: { downloadUrl: '/pdf', path: 'reports/revision-2/运营报告.pdf', size: 1536 },
      word: { downloadUrl: '/word', path: 'reports/revision-2/运营报告.docx', size: 2048 },
      editor: { openUrl: '/editor/2' },
    })

    expect(panel.dialog.hidden).toBe(false)
    expect(panel.dialog.querySelector<HTMLAnchorElement>('[data-format="pdf"]')?.href).toContain(
      '/pdf',
    )
    expect(panel.dialog.textContent).toContain('版本 2')
    expect(panel.dialog.textContent).toContain('运营报告.pdf · 1.5 KB')
    expect(panel.dialog.textContent).toContain('运营报告.docx · 2 KB')
    expect(panel.dialog.textContent).toContain('请求编号：01995f3d-7bd2-7000-8000-000000000001')

    panel.close.click()
    expect(panel.dialog.hidden).toBe(true)
  })

  it('highlights the export format requested by the user', () => {
    const panel = createExportPanel()
    panel.show(
      { revision: 2, pdf: { downloadUrl: '/pdf' }, word: { downloadUrl: '/word' } },
      'word',
    )
    expect(panel.dialog.querySelector('#export-title')?.textContent).toBe('Word 导出完成')
    expect(panel.dialog.querySelector('[data-format="word"]')?.classList).toContain('is-primary')
    expect(panel.dialog.querySelector('[data-format="pdf"]')?.classList).not.toContain('is-primary')
  })

  it('copies an exported artifact link with feedback', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const panel = createExportPanel()
    panel.show({ revision: 2, pdf: { downloadUrl: '/pdf' }, word: { downloadUrl: '/word' } })

    panel.dialog.querySelector<HTMLButtonElement>('[data-copy="pdf"]')!.click()
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('/pdf'))
    expect(panel.dialog.querySelector('.export-copy-status')?.textContent).toBe('PDF 链接已复制')
  })

  it('clears copy feedback when showing a new export result', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const panel = createExportPanel()
    panel.show({ revision: 2, pdf: { downloadUrl: '/pdf' }, word: { downloadUrl: '/word' } })

    panel.dialog.querySelector<HTMLButtonElement>('[data-copy="pdf"]')!.click()
    await vi.waitFor(() => expect(panel.dialog.querySelector('.export-copy-status')?.textContent).toBe('PDF 链接已复制'))

    panel.show({ revision: 3, pdf: { downloadUrl: '/pdf-3' }, word: { downloadUrl: '/word-3' } })

    expect(panel.dialog.querySelector('.export-copy-status')?.textContent).toBe('')
  })

  it('closes the export result panel with Escape', () => {
    const panel = createExportPanel()
    panel.show({ revision: 2, pdf: { downloadUrl: '/pdf' }, word: { downloadUrl: '/word' } })
    expect(panel.dialog.hidden).toBe(false)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(panel.dialog.hidden).toBe(true)
  })

  it('shows and closes keyboard shortcut help', () => {
    const panel = createShortcutsPanel()
    panel.open()
    expect(panel.dialog.hidden).toBe(false)
    expect(panel.dialog.textContent).toContain('Ctrl / ⌘ + S')
    expect(panel.dialog.textContent).toContain('专注模式')
    panel.close.click()
    expect(panel.dialog.hidden).toBe(true)
  })

  it('shows offline state and retries on reconnect', () => {
    const label = document.createElement('span')
    const reconnect = vi.fn()
    createNetworkStatusController(label, reconnect)

    window.dispatchEvent(new Event('offline'))
    expect(label.textContent).toBe('离线待同步')
    expect(label.classList).toContain('is-offline')
    window.dispatchEvent(new Event('online'))
    expect(label.textContent).toBe('网络已连接')
    expect(reconnect).toHaveBeenCalledOnce()
  })
})
