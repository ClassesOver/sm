import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createMoreActionsController,
  createNetworkStatusController,
  createFocusModeController,
  createExportPanel,
  createImagePreview,
  createViewModeController,
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

  it('starts desktop editing in wide mode and can switch to A4', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.querySelector<HTMLButtonElement>('#view')!
    createViewModeController(root, toggle)

    expect(root.classList).toContain('view-wide')
    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    toggle.click()

    expect(root.classList).toContain('view-a4')
    expect(root.classList).not.toContain('view-wide')
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
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

  it('opens and closes a static image preview', () => {
    const preview = createImagePreview(document.querySelector<HTMLElement>('#editor')!)
    document.querySelector<HTMLImageElement>('#editor img')!.click()

    expect(preview.dialog.hidden).toBe(false)
    expect(preview.dialog.querySelector('img')?.getAttribute('src')).toBe('chart.png')

    preview.close.click()
    expect(preview.dialog.hidden).toBe(true)
  })

  it('enters focus mode with a shortcut and exits with Escape', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    createFocusModeController(root)

    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, shiftKey: true }),
    )
    expect(root.classList).toContain('focus-mode')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(root.classList).not.toContain('focus-mode')
  })

  it('toggles focus mode from visible controls', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    const toggle = document.createElement('button')
    const exit = document.createElement('button')
    createFocusModeController(root, toggle, exit)
    toggle.click()
    expect(root.classList).toContain('focus-mode')
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    exit.click()
    expect(root.classList).not.toContain('focus-mode')
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
    expect(panel.dialog.textContent).toContain('Revision 2')
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
