import '@milkdown/crepe/theme/common/prosemirror.css'
import '@milkdown/crepe/theme/common/reset.css'
import '@milkdown/crepe/theme/common/block-edit.css'
import '@milkdown/crepe/theme/common/cursor.css'
import '@milkdown/crepe/theme/common/link-tooltip.css'
import '@milkdown/crepe/theme/common/list-item.css'
import '@milkdown/crepe/theme/common/placeholder.css'
import '@milkdown/crepe/theme/common/toolbar.css'
import '@milkdown/crepe/theme/common/table.css'
import '@milkdown/crepe/theme/common/ai.css'
import '@milkdown/crepe/theme/common/diff.css'
import '@milkdown/crepe/theme/frame.css'
import './style.css'

import { editorViewCtx } from '@milkdown/kit/core'
import { outline } from '@milkdown/kit/utils'
import { replaceAll } from '@milkdown/kit/utils'
import {
  createIcons,
  FileDown,
  FileText,
  Focus,
  History,
  Keyboard,
  Maximize2,
  MoreHorizontal,
  PanelLeft,
  Save,
  Search,
  Settings2,
  X,
} from 'lucide'

import { ReportEditorApiError, ReportEditorClient } from './api'
import { configureSelectionAISuggestions, selectionAIProvider } from './ai'
import { runInBackground } from './background'
import {
  createFocusModeController,
  createMoreActionsController,
  createNetworkStatusController,
  createExportPanel,
  createImagePreview,
  createEditorPreferenceController,
  installEditorShortcuts,
} from './enhancements'
import { protocolMarkerPlugin } from './protocol-plugin'
import { restoreProtocolMarkers } from './protocol'
import { findDocumentMatches, replaceDocumentMatches } from './search-document'
import { searchHighlightPlugin, searchHighlightPluginKey } from './search-highlight-plugin'
import { createEditorShell } from './shell'
import { createOutlineController, type OutlineItem } from './outline'
import { documentMetrics } from './metrics'
import { headingStructureStatus } from './structure'
import { createLocalDraftController } from './draft'
import { createBackToTopController, createScrollProgressController } from './progress'
import { imageDescriptionStatus } from './content-quality'
import { createConflictPanel } from './conflict-panel'
import { createExportSettingsPanel, type ExportSettings } from './export-settings'
import { toolbarMode } from './viewport'
import { createLoadStatePanel } from './load-state'
import { createSaveStateTracker, type SaveStateTracker } from './save-state'
import { createTelemetryReporter } from './telemetry'
import { errorLabel } from './error-labels'
import { formalHeadings, reportPreflight, showPreflightPanel } from './preflight'
import { editorChineseLocale, formatRevisionLabel } from './localization'
import { createReportEditor } from './editor-features'

const root = document.querySelector<HTMLElement>('#app')
if (!root) throw new Error('report editor root is missing')

const basePath = window.location.pathname.replace(/\/$/, '')
const parts = basePath.split('/')
const revision = parts.at(-1) ?? ''
const shell = createEditorShell(root, toolbarMode(window.innerWidth))
const loadState = createLoadStatePanel(root)
loadState.showLoading()
const progressBar = root.querySelector<HTMLElement>('.reading-progress')
if (progressBar) createScrollProgressController(progressBar)
const backToTop = root.querySelector<HTMLButtonElement>('.back-to-top')
if (backToTop) createBackToTopController(backToTop)
createMoreActionsController(root, shell.more)
let shortcutsPanelPromise: Promise<{ open(): void }> | null = null
shell.shortcuts.addEventListener('click', async () => {
  shortcutsPanelPromise ??= import('./shortcuts').then(({ createShortcutsPanel }) =>
    createShortcutsPanel(),
  )
  const panel = await shortcutsPanelPromise
  panel.open()
})
const preferences = createEditorPreferenceController(root, shell.viewToggle, basePath)
createFocusModeController(root, shell.focus, shell.focusExit)
const exportPanel = createExportPanel()
const exportSettingsPanel = createExportSettingsPanel(root)
let pendingExportSettings: ExportSettings | null = null
shell.exportSettings.addEventListener('click', () => exportSettingsPanel.open())
exportSettingsPanel.dialog.querySelector('[data-export-settings="confirm"]')?.addEventListener('click', () => {
  pendingExportSettings = exportSettingsPanel.read()
  exportSettingsPanel.close()
})
let getEditorMarkdown = () => ''
let initialFormalHeadings: string[] | undefined
const currentSectionLabel = root.querySelector<HTMLElement>('.current-section')
const outlineController = createOutlineController({
  container: shell.outline,
  editor: shell.editor,
  toggle: shell.outlineToggle,
  // 正式章节（h2-h4）的顺序与编号由服务端批准提纲锁定，导出会逐项核对；
  // 大纲拖拽重排必然导致导出失败，且会让章节标识错位，因此只保留导航。
  initialCollapsed: preferences.outlineCollapsed || undefined,
  onCollapsedChange: preferences.setOutlineCollapsed,
  onActive: (item) => {
    if (currentSectionLabel) currentSectionLabel.textContent = `当前位置：${item.text}`
  },
})
const revisionLabel = root.querySelector<HTMLElement>('.revision-label')
const metricsLabel = root.querySelector<HTMLElement>('.doc-metrics')
const structureLabel = root.querySelector<HTMLElement>('.structure-status')
const imageQualityLabel = root.querySelector<HTMLElement>('.image-quality-status')
if (revisionLabel) revisionLabel.textContent = formatRevisionLabel(revision)
createIcons({
  icons: {
    FileDown,
    FileText,
    Focus,
    History,
    Keyboard,
    Maximize2,
    MoreHorizontal,
    PanelLeft,
    Save,
    Search,
    Settings2,
    X,
  },
})

const base = document.createElement('base')
base.href = `${basePath}/asset/`
document.head.prepend(base)

const client = new ReportEditorClient(basePath)
const telemetry = createTelemetryReporter((payload) => client.reportEvent(payload))
const loadStartedAt = performance.now()
let conflictPanel: ReturnType<typeof createConflictPanel> | null = null
let sha256 = ''
let lastSavedMarkdown = ''
let currentMarkdown = ''
let saveTimer: number | undefined
let savePromise: Promise<void> | null = null
let retryAction: (() => void) | null = null
let draftController: ReturnType<typeof createLocalDraftController> | null = null
let outlineFrame: number | undefined
let saveState: SaveStateTracker | null = null

function updateOutline(items: OutlineItem[]) {
  outlineController.update(items)
  const structure = headingStructureStatus(items)
  if (structureLabel) {
    structureLabel.textContent = structure.label
    structureLabel.classList.toggle('is-warning', structure.warning)
  }
  const imageQuality = imageDescriptionStatus(shell.editor)
  if (imageQualityLabel) {
    imageQualityLabel.textContent = imageQuality.label
    imageQualityLabel.classList.toggle('is-warning', imageQuality.warning)
  }
}

function status(
  label: string,
  state: 'idle' | 'busy' | 'dirty' | 'error' = 'idle',
  retry: (() => void) | null = null,
) {
  shell.statusLabel.textContent = label
  shell.status.dataset.state = state
  shell.status.setAttribute('title', state === 'busy'
    ? '正在处理，请稍候'
    : state === 'dirty'
      ? '修改会自动保存，也可以使用保存按钮立即保存'
      : state === 'error'
        ? '操作未完成，可点击重试或查看提示'
        : '内容已保存，可继续编辑')
  shell.status.setAttribute('aria-busy', String(state === 'busy'))
  shell.editor.setAttribute('aria-busy', String(state === 'busy'))
  retryAction = retry
  shell.retry.hidden = retry === null
}

function savedLabel(): string {
  return saveState?.savedLabel() ?? '已保存'
}

shell.retry.addEventListener('click', () => retryAction?.())

function setActionsDisabled(disabled: boolean) {
  shell.save.disabled = disabled
  shell.exportPdf.disabled = disabled
  shell.exportWord.disabled = disabled
}

function errorStatusLabel(error: unknown): string {
  const label = errorLabel(error)
  return error instanceof ReportEditorApiError && error.requestId
    ? `${label} · 请求编号 ${error.requestId}`
    : label
}

try {
  const documentState = await client.load()
  const saveInBackground = () => runInBackground(saveNow())
  void telemetry.record({
    event: 'document_loaded',
    durationMs: Math.round(performance.now() - loadStartedAt),
  })
  conflictPanel = createConflictPanel(root, {
    keepLocal: saveInBackground,
    useRemote: () => void recoverFromConflict(),
    mergeAndRetry: (markdown) => {
      crepe.editor.action(replaceAll(markdown))
      saveInBackground()
    },
  })
  sha256 = documentState.sha256
  lastSavedMarkdown = documentState.markdown
  currentMarkdown = documentState.markdown
  saveState = createSaveStateTracker(documentState.markdown)
  const crepe = createReportEditor(
    shell.editor,
    documentState.markdown,
    {
      ...editorChineseLocale.ai,
      provider: selectionAIProvider(client),
      buildAISuggestions: configureSelectionAISuggestions,
      diffReviewOnEnd: true,
      onError: () => status('AI 改写失败', 'error'),
    },
  )
  crepe.editor.use(protocolMarkerPlugin)
  crepe.editor.use(searchHighlightPlugin)
  getEditorMarkdown = () => restoreProtocolMarkers(crepe.getMarkdown())
  await crepe.create()
  crepe.on((listener) => {
    listener.markdownUpdated((_ctx, serialized) => {
      // Milkdown 序列化会把协议标记转义为 \[\[...]]；变更检测、本地草稿和保存必须
      // 统一使用还原后的 Markdown，否则服务端导出找不到章节标识。
      const markdown = restoreProtocolMarkers(serialized)
      if (metricsLabel) metricsLabel.textContent = documentMetrics(markdown)
      if (outlineFrame !== undefined) window.cancelAnimationFrame(outlineFrame)
      outlineFrame = window.requestAnimationFrame(() => {
        outlineFrame = undefined
        updateOutline(crepe.editor.action(outline()))
      })
      currentMarkdown = markdown
      saveState?.edit(markdown)
      if (markdown === lastSavedMarkdown) {
        draftController?.clear()
        status(savedLabel())
        return
      }
      draftController?.store(markdown)
      status(saveState?.dirtyLabel(!navigator.onLine) ?? '有未保存更改', 'dirty')
      window.clearTimeout(saveTimer)
      saveTimer = window.setTimeout(saveInBackground, 800)
    })
  })
  if (documentState.interactiveCharts && Object.keys(documentState.interactiveCharts).length) {
    const { createInteractiveCharts } = await import('./interactive-charts')
    void createInteractiveCharts(shell.editor, documentState.interactiveCharts, basePath).refresh()
  }
  loadState.hide()
  const [
    { createSearchController },
    { createHistoryController, createPersistedHistoryLoader },
  ] = await Promise.all([
    import('./search'),
    import('./history'),
  ])
  const searchController = createSearchController({
    root,
    getText: () => getEditorMarkdown(),
    replaceText: (markdown) => crepe.editor.action(replaceAll(markdown)),
    backend: {
      count: (query) =>
        crepe.editor.action((ctx) => findDocumentMatches(ctx.get(editorViewCtx).state.doc, query).length),
      replace: (query, replacement, index) => {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx)
          const matches = findDocumentMatches(view.state.doc, query)
          const selected = index === null ? matches : matches.slice(index, index + 1)
          if (selected.length) view.dispatch(replaceDocumentMatches(view.state.tr, selected, replacement))
        })
      },
    },
    applyHighlight: (query, current) => {
      crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx)
        view.dispatch(view.state.tr.setMeta(searchHighlightPluginKey, { query, current }))
      })
    },
  })
  searchController.setEditor(shell.editor)
  shell.search.addEventListener('click', () => searchController.open())
  const historyController = createHistoryController(
    root,
    (markdown) => {
      crepe.editor.action(replaceAll(markdown))
      status('历史版本已恢复为草稿', 'dirty')
    },
    async (historyRevision) => (await client.historyRevision(historyRevision)).markdown,
    createPersistedHistoryLoader((limit, offset) => client.historyPage(limit, offset)),
  )
  shell.history.addEventListener('click', () => historyController.open())
  draftController = createLocalDraftController(
    root,
    `smart-reporting-editor:${basePath}`,
    (markdown) => crepe.editor.action(replaceAll(markdown)),
  )
  draftController.offer(documentState.markdown)
  initialFormalHeadings = formalHeadings(documentState.markdown)
  if (metricsLabel) metricsLabel.textContent = documentMetrics(documentState.markdown)
  historyController.record(`${formatRevisionLabel(revision)} · 初始版本`, documentState.markdown)
  createImagePreview(shell.editor)
  updateOutline(crepe.editor.action(outline()))
  window.addEventListener(
    'scroll',
    () => {
      const headings = Array.from(
        shell.editor.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6'),
      )
      let active = 0
      headings.forEach((heading, index) => {
        if (heading.getBoundingClientRect().top <= 120) active = index
      })
      outlineController.setActive(active)
    },
    { passive: true },
  )
  status(savedLabel())
  const saveScroll = () => preferences.saveScroll(window.scrollY)
  window.addEventListener('scroll', saveScroll, { passive: true })
  preferences.restoreScroll()

  async function saveNow(): Promise<void> {
    window.clearTimeout(saveTimer)
    if (savePromise) {
      await savePromise
      if (currentMarkdown !== lastSavedMarkdown) return saveNow()
      return
    }
    const markdown = getEditorMarkdown()
    currentMarkdown = markdown
    if (markdown === lastSavedMarkdown) return
    status('保存中', 'busy')
    saveState?.beginSave()
    const saveStartedAt = performance.now()
    const savingMarkdown = markdown
    savePromise = client
      .save(savingMarkdown, sha256)
      .then(async (saved) => {
        const remainingFeedbackTime = 320 - (performance.now() - saveStartedAt)
        if (remainingFeedbackTime > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, remainingFeedbackTime))
        }
        sha256 = saved.sha256
        lastSavedMarkdown = savingMarkdown
        saveState?.saved(savingMarkdown)
        if (currentMarkdown === savingMarkdown) draftController?.clear()
        historyController.record(savedLabel(), savingMarkdown)
        void telemetry.record({
          event: 'save_succeeded',
          durationMs: Math.round(performance.now() - saveStartedAt),
        })
        status(
          currentMarkdown === savingMarkdown ? savedLabel() : '有未保存更改',
          currentMarkdown === savingMarkdown ? 'idle' : 'dirty',
        )
      })
      .catch(async (error: unknown) => {
        saveState?.saveFailed()
        void telemetry.record({
          event: 'save_failed',
          durationMs: Math.round(performance.now() - saveStartedAt),
          errorCode: error instanceof ReportEditorApiError ? error.code : 'report_editor_save_failed',
        })
        if (error instanceof ReportEditorApiError && error.status === 409) {
          try {
            const remote = await client.load()
            sha256 = remote.sha256
            conflictPanel?.show(lastSavedMarkdown, savingMarkdown, remote.markdown)
            status('保存冲突 · 请选择本地或远端版本', 'error')
          } catch {
            status('保存冲突 · 点击重试载入远端', 'error', () => void recoverFromConflict())
          }
        } else {
          status(errorLabel(error), 'error', saveInBackground)
        }
        throw error
      })
      .finally(() => {
        savePromise = null
      })
    await savePromise
  }

  const networkLabel = root.querySelector<HTMLElement>('.network-status')
  if (networkLabel) {
    createNetworkStatusController(networkLabel, () => {
      if (currentMarkdown !== lastSavedMarkdown) saveInBackground()
    })
    window.addEventListener('offline', () => {
      if (currentMarkdown !== lastSavedMarkdown) {
        status(saveState?.dirtyLabel(true) ?? '离线 · 更改待同步', 'dirty')
      }
    })
  }

  async function recoverFromConflict(): Promise<void> {
    status('载入远端版本', 'busy')
    try {
      const latest = await client.load()
      crepe.editor.action(replaceAll(latest.markdown))
      sha256 = latest.sha256
      lastSavedMarkdown = latest.markdown
      currentMarkdown = latest.markdown
      saveState?.reset(latest.markdown)
      status(savedLabel())
    } catch (error) {
      status(errorLabel(error), 'error', () => void recoverFromConflict())
    }
  }

  async function exportFormat(format: 'pdf' | 'word') {
    const formatLabel = format === 'pdf' ? 'PDF' : 'Word'
    const exportStartedAt = performance.now()
    setActionsDisabled(true)
    status(`准备导出 ${formatLabel}`, 'busy')
    try {
      const warnings = reportPreflight(getEditorMarkdown(), shell.editor, initialFormalHeadings)
      if (warnings.length) {
        const proceed = await new Promise<boolean>((resolve) => showPreflightPanel(root!, warnings, resolve))
        if (!proceed) return
      }
      await saveNow()
      status(`正在生成 ${formatLabel}`, 'busy')
      const { note = '', ...settings } = pendingExportSettings ?? {
        cover: false,
        toc: true,
        headerFooter: true,
        pageNumbers: true,
        note: '',
      }
      const result = await client.export(sha256, settings, note)
      void telemetry.record({
        event: 'export_succeeded',
        durationMs: Math.round(performance.now() - exportStartedAt),
        format,
      })
      status(`${formatLabel} 导出完成`)
      exportPanel.show(result, format)
    } catch (error) {
      void telemetry.record({
        event: 'export_failed',
        durationMs: Math.round(performance.now() - exportStartedAt),
        format,
        errorCode: error instanceof ReportEditorApiError ? error.code : 'report_editor_export_failed',
      })
      status(`${formatLabel} 导出失败：${errorStatusLabel(error)}`, 'error', () => void exportFormat(format))
    } finally {
      setActionsDisabled(false)
    }
  }

  shell.save.addEventListener('click', saveInBackground)
  shell.exportPdf.addEventListener('click', () => void exportFormat('pdf'))
  shell.exportWord.addEventListener('click', () => void exportFormat('word'))
  installEditorShortcuts({
    save: saveInBackground,
    exportPdf: () => void exportFormat('pdf'),
  })
  window.addEventListener('beforeunload', (event) => {
    if (saveState?.shouldWarnBeforeUnload) event.preventDefault()
  })
} catch (error) {
  status(errorLabel(error), 'error', () => window.location.reload())
  loadState.showError(error, () => window.location.reload())
  setActionsDisabled(true)
}
