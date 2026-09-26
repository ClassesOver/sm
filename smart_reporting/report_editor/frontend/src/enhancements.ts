import { createModal } from './modal'
import { formatRevisionLabel } from './localization'
import { readStorage, writeStorage } from './storage'

type EditorPreferences = { view: 'wide' | 'a4'; outlineCollapsed: boolean }
export function createEditorPreferenceController(root: HTMLElement, toggle: HTMLButtonElement, key: string) {
  const storageKey = `smart-reporting-editor:prefs:${key}`
  let prefs: EditorPreferences = { view: 'wide', outlineCollapsed: false }
  try {
    const saved = JSON.parse(readStorage(storageKey) ?? '{}') as Record<string, unknown>
    if (saved.view === 'wide' || saved.view === 'a4') prefs.view = saved.view
    if (typeof saved.outlineCollapsed === 'boolean') {
      prefs.outlineCollapsed = saved.outlineCollapsed
    }
  } catch { /* ignore malformed preference */ }
  const persist = () => {
    writeStorage(storageKey, JSON.stringify(prefs))
  }
  const setOutlineCollapsed = (collapsed: boolean, shouldPersist = true) => {
    prefs.outlineCollapsed = collapsed
    root.classList.toggle('outline-collapsed', collapsed)
    root.querySelector('.report-workspace')?.classList.toggle('outline-collapsed', collapsed)
    if (shouldPersist) persist()
  }
  const setView = (view: 'wide' | 'a4', shouldPersist = true) => {
    prefs.view = view
    root.classList.toggle('view-a4', view === 'a4')
    root.classList.toggle('view-wide', view === 'wide')
    toggle.setAttribute('aria-pressed', String(view === 'a4'))
    const label = toggle.querySelector('span')
    if (label) label.textContent = view === 'a4' ? 'A4' : '宽屏'
    if (shouldPersist) persist()
  }
  setView(prefs.view, false)
  setOutlineCollapsed(prefs.outlineCollapsed, false)
  toggle.addEventListener('click', () => setView(prefs.view === 'a4' ? 'wide' : 'a4'))
  const scrollKey = `${storageKey}:scroll`
  return {
    get outlineCollapsed() {
      return prefs.outlineCollapsed
    },
    setView,
    setOutlineCollapsed,
    saveScroll: (top: number) => {
      writeStorage(scrollKey, String(Math.max(0, Math.round(top))))
    },
    restoreScroll: () => {
      const top = Number(readStorage(scrollKey))
      if (Number.isFinite(top) && top > 0) window.scrollTo({ top, behavior: 'auto' })
    },
  }
}

export function createMoreActionsController(root: HTMLElement, toggle: HTMLButtonElement) {
  const close = (restoreFocus = false) => {
    root.classList.remove('more-actions-open')
    toggle.setAttribute('aria-expanded', 'false')
    if (restoreFocus) toggle.focus()
  }
  toggle.addEventListener('click', (event) => {
    event.stopPropagation()
    const expanded = root.classList.toggle('more-actions-open')
    toggle.setAttribute('aria-expanded', String(expanded))
    if (expanded) {
      root.querySelector<HTMLButtonElement>('.secondary-actions button:not([disabled])')?.focus()
    }
  })
  root.querySelector('.secondary-actions')?.addEventListener('click', () => close())
  document.addEventListener('click', () => close())
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && root.classList.contains('more-actions-open')) close(true)
  })
  return { close }
}

export function createNetworkStatusController(label: HTMLElement, onReconnect: () => void) {
  const offline = () => {
    label.textContent = '离线待同步'
    label.classList.add('is-offline')
  }
  const online = () => {
    label.textContent = '网络已连接'
    label.classList.remove('is-offline')
    onReconnect()
  }
  window.addEventListener('offline', offline)
  window.addEventListener('online', online)
  if (!navigator.onLine) offline()
  else label.textContent = '网络已连接'
  return {
    dispose() {
      window.removeEventListener('offline', offline)
      window.removeEventListener('online', online)
    },
  }
}

export function installEditorShortcuts(actions: {
  save: () => void
  exportPdf: () => void
}) {
  const listener = (event: KeyboardEvent) => {
    if (!(event.ctrlKey || event.metaKey)) return
    if (event.key.toLowerCase() === 's') {
      event.preventDefault()
      actions.save()
    } else if (event.shiftKey && event.key.toLowerCase() === 'e') {
      event.preventDefault()
      actions.exportPdf()
    }
  }
  window.addEventListener('keydown', listener)
  return () => window.removeEventListener('keydown', listener)
}

export function createFocusModeController(
  root: HTMLElement,
  toggle?: HTMLButtonElement,
  exit?: HTMLButtonElement,
) {
  let previousFocus: HTMLElement | null = null
  const setFocus = (enabled: boolean) => {
    const focusExit = enabled && Boolean(exit && document.activeElement === toggle)
    if (enabled && !root.classList.contains('focus-mode')) {
      const active = document.activeElement
      previousFocus = active instanceof HTMLElement && active !== document.body ? active : null
    }
    root.classList.toggle('focus-mode', enabled)
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(enabled))
      toggle.setAttribute('aria-label', enabled ? '退出专注模式' : '进入专注模式')
      toggle.title = enabled ? '退出专注模式' : '专注模式'
      const label = toggle.querySelector('span')
      if (label) label.textContent = enabled ? '退出专注' : '专注'
    }
    if (exit) {
      exit.setAttribute('aria-label', '退出专注模式')
      exit.title = '退出专注模式'
      if (focusExit) exit.focus()
    }
    if (!enabled) {
      previousFocus?.focus()
      previousFocus = null
    }
  }
  setFocus(root.classList.contains('focus-mode'))
  toggle?.addEventListener('click', () => setFocus(!root.classList.contains('focus-mode')))
  exit?.addEventListener('click', () => setFocus(false))
  const listener = (event: KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'f') {
      event.preventDefault()
      setFocus(!root.classList.contains('focus-mode'))
    } else if (event.key === 'Escape' && root.classList.contains('focus-mode')) {
      setFocus(false)
    }
  }
  window.addEventListener('keydown', listener)
  return { setFocus, dispose: () => window.removeEventListener('keydown', listener) }
}

export function createImagePreview(editor: HTMLElement) {
  const modal = createModal({ root: document.body, overlayClass: 'image-preview', closeClass: 'image-preview-close', closeLabel: '关闭图片预览', label: '图片预览', variant: 'media', content: `
    <figure><img alt=""><figcaption></figcaption></figure>
  ` })
  const dialog = modal.overlay
  const image = dialog.querySelector<HTMLImageElement>('img')!
  const caption = dialog.querySelector<HTMLElement>('figcaption')!
  const close = modal.closeButton!
  let opener: HTMLElement | null = null
  const isPreviewable = (target: EventTarget | null): target is HTMLImageElement =>
    target instanceof HTMLImageElement && !target.classList.contains('interactive-chart-fallback')
  const prepareImage = (target: HTMLImageElement) => {
    if (isPreviewable(target)) target.tabIndex = 0
  }
  const show = (target: HTMLImageElement) => {
    opener = target
    image.src = target.getAttribute('src') ?? ''
    image.alt = target.alt
    caption.textContent = target.alt
    caption.hidden = !target.alt
    modal.open(close)
  }
  const hide = () => {
    modal.close()
    opener = null
  }
  close.addEventListener('click', hide)
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) hide()
  })
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !dialog.hidden) hide()
  })
  editor.querySelectorAll<HTMLImageElement>('img').forEach(prepareImage)
  new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node instanceof HTMLImageElement) prepareImage(node)
      else if (node instanceof Element) node.querySelectorAll<HTMLImageElement>('img').forEach(prepareImage)
    }))
  }).observe(editor, { childList: true, subtree: true })
  editor.addEventListener('click', (event) => {
    if (isPreviewable(event.target)) show(event.target)
  })
  editor.addEventListener('keydown', (event) => {
    if (!isPreviewable(event.target) || (event.key !== 'Enter' && event.key !== ' ')) return
    event.preventDefault()
    show(event.target)
  })
  return { dialog, close }
}

interface ExportPanelResult {
  revision: number
  requestId?: string
  pdf: { downloadUrl: string; path?: string; size?: number }
  word: { downloadUrl: string; path?: string; size?: number }
  editor?: { openUrl: string }
}

function exportArtifactLabel(
  format: 'pdf' | 'word',
  artifact: { downloadUrl: string; path?: string; size?: number },
): string {
  const fallback = format === 'pdf' ? 'report.pdf' : 'report.docx'
  const filename = artifact.path?.split('/').at(-1) || fallback
  if (!artifact.size) return filename
  const size = artifact.size < 1024
    ? `${artifact.size} B`
    : artifact.size < 1024 * 1024
      ? `${Number((artifact.size / 1024).toFixed(1))} KB`
      : `${Number((artifact.size / 1024 / 1024).toFixed(1))} MB`
  return `${filename} · ${size}`
}

export function createExportPanel() {
  const modal = createModal({ root: document.body, overlayClass: 'export-panel', cardClass: 'export-panel-card', closeClass: 'export-panel-close', closeLabel: '关闭导出结果', labelledBy: 'export-title', content: `
      <div class="export-success-mark" aria-hidden="true">✓</div>
      <h2 id="export-title">导出完成</h2>
      <p class="export-revision"></p>
      <p class="export-note">已生成新的报告版本，旧版本不会被覆盖。</p>
      <div class="export-links">
        <div class="export-format-row"><a data-format="pdf" target="_blank" rel="noreferrer">下载 PDF</a><span data-artifact-meta="pdf"></span><button type="button" data-copy="pdf">复制链接</button></div>
        <div class="export-format-row"><a data-format="word" target="_blank" rel="noreferrer">下载 Word</a><span data-artifact-meta="word"></span><button type="button" data-copy="word">复制链接</button></div>
        <a data-format="editor">继续编辑新版本</a>
      </div>
      <p class="export-request-id"></p>
      <p class="export-copy-status" aria-live="polite"></p>
  ` })
  const dialog = modal.overlay
  const close = modal.closeButton!
  dialog.querySelectorAll<HTMLButtonElement>('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const format = button.dataset.copy as 'pdf' | 'word'
      const link = dialog.querySelector<HTMLAnchorElement>(`[data-format="${format}"]`)
      const status = dialog.querySelector<HTMLElement>('.export-copy-status')!
      try {
        await navigator.clipboard.writeText(link?.getAttribute('href') ?? '')
        status.textContent = `${format === 'pdf' ? 'PDF' : 'Word'} 链接已复制`
      } catch {
        status.textContent = '复制失败，请直接打开下载链接'
      }
    })
  })
  return {
    dialog,
    close,
    show(result: ExportPanelResult, preferredFormat: 'pdf' | 'word' = 'pdf') {
      dialog.querySelector<HTMLElement>('#export-title')!.textContent =
        `${preferredFormat === 'pdf' ? 'PDF' : 'Word'} 导出完成`
      dialog.querySelector<HTMLElement>('.export-revision')!.textContent =
        `${formatRevisionLabel(result.revision)} 已生成`
      const pdf = dialog.querySelector<HTMLAnchorElement>('[data-format="pdf"]')!
      const word = dialog.querySelector<HTMLAnchorElement>('[data-format="word"]')!
      pdf.href = result.pdf.downloadUrl
      word.href = result.word.downloadUrl
      dialog.querySelector<HTMLElement>('[data-artifact-meta="pdf"]')!.textContent =
        exportArtifactLabel('pdf', result.pdf)
      dialog.querySelector<HTMLElement>('[data-artifact-meta="word"]')!.textContent =
        exportArtifactLabel('word', result.word)
      const requestId = dialog.querySelector<HTMLElement>('.export-request-id')!
      requestId.textContent = result.requestId ? `请求编号：${result.requestId}` : ''
      requestId.hidden = !result.requestId
      dialog.querySelector<HTMLElement>('.export-copy-status')!.textContent = ''
      pdf.classList.toggle('is-primary', preferredFormat === 'pdf')
      word.classList.toggle('is-primary', preferredFormat === 'word')
      const editor = dialog.querySelector<HTMLAnchorElement>('[data-format="editor"]')!
      editor.hidden = !result.editor?.openUrl
      if (result.editor?.openUrl) editor.href = result.editor.openUrl
      modal.open(close)
    },
  }
}
