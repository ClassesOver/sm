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

import { CrepeBuilder } from '@milkdown/crepe/builder'
import { ai } from '@milkdown/crepe/feature/ai'
import { blockEdit } from '@milkdown/crepe/feature/block-edit'
import { cursor } from '@milkdown/crepe/feature/cursor'
import { linkTooltip } from '@milkdown/crepe/feature/link-tooltip'
import { listItem } from '@milkdown/crepe/feature/list-item'
import { placeholder } from '@milkdown/crepe/feature/placeholder'
import { table } from '@milkdown/crepe/feature/table'
import { toolbar } from '@milkdown/crepe/feature/toolbar'
import { outline } from '@milkdown/kit/utils'
import { replaceAll } from '@milkdown/kit/utils'
import {
  createIcons,
  FileDown,
  FileText,
  Focus,
  History,
  Keyboard,
  LayoutTemplate,
  Maximize2,
  MoreHorizontal,
  PanelLeft,
  Save,
  Search,
  Settings2,
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
import { showEditorOnboarding } from './onboarding'
import { reportPreflight, showPreflightPanel } from './preflight'

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
let replaceEditorMarkdown: (markdown: string) => void = () => {}
const currentSectionLabel = root.querySelector<HTMLElement>('.current-section')
const outlineController = createOutlineController({
  container: shell.outline,
  editor: shell.editor,
  toggle: shell.outlineToggle,
  getMarkdown: () => getEditorMarkdown(),
  replaceMarkdown: (markdown) => replaceEditorMarkdown(markdown),
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
if (revisionLabel) revisionLabel.textContent = `Revision ${revision}`
createIcons({
  icons: {
    FileDown,
    FileText,
    Focus,
    History,
    Keyboard,
    LayoutTemplate,
    Maximize2,
    MoreHorizontal,
    PanelLeft,
    Save,
    Search,
    Settings2,
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

function errorLabel(error: unknown): string {
  if (error instanceof ReportEditorApiError && error.status === 409) return '保存冲突'
  if (error instanceof ReportEditorApiError && error.status === 410) return '会话已过期'
  if (error instanceof TypeError) return '无法连接报告服务'
  return '操作失败'
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
  const crepe = new CrepeBuilder({
    root: shell.editor,
    defaultValue: documentState.markdown,
  })
    .addFeature(cursor)
    .addFeature(listItem)
    .addFeature(linkTooltip)
    .addFeature(blockEdit)
    .addFeature(placeholder, { text: '开始编辑报告...' })
    .addFeature(toolbar)
    .addFeature(table)
    .addFeature(ai, {
      provider: selectionAIProvider(client),
      buildAISuggestions: configureSelectionAISuggestions,
      diffReviewOnEnd: true,
      suggestionsHeaderLabel: '选择改写方式',
      listboxLabel: 'AI 改写方式',
      streamingIndicator: {
        fallbackLabel: '正在改写',
        cancelHint: '按 Esc 取消',
      },
      diff: {
        acceptLabel: '接受',
        rejectLabel: '拒绝',
      },
      diffActions: {
        retryLabel: '重试',
        rejectAllLabel: '全部拒绝',
        acceptAllLabel: '全部接受',
      },
      onError: () => status('AI 改写失败', 'error'),
    })
  crepe.editor.use(protocolMarkerPlugin)
  getEditorMarkdown = () => crepe.getMarkdown()
  replaceEditorMarkdown = (markdown) => crepe.editor.action(replaceAll(markdown))
  crepe.on((listener) => {
    listener.markdownUpdated((_ctx, markdown) => {
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
  await crepe.create()
  if (documentState.interactiveCharts && Object.keys(documentState.interactiveCharts).length) {
    const { createInteractiveCharts } = await import('./interactive-charts')
    void createInteractiveCharts(shell.editor, documentState.interactiveCharts, basePath).refresh()
  }
  loadState.hide()
  showEditorOnboarding(root, basePath)
  const [
    { createSearchController },
    { createHistoryController, createPersistedHistoryLoader },
  ] = await Promise.all([
    import('./search'),
    import('./history'),
  ])
  const searchController = createSearchController({
    root,
    getText: () => crepe.getMarkdown(),
    replaceText: (markdown) => crepe.editor.action(replaceAll(markdown)),
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
  let templatePanelPromise: Promise<{ open(): void }> | null = null
  shell.templates.addEventListener('click', async () => {
    templatePanelPromise ??= import('./templates').then(({ createTemplatePanel }) =>
      createTemplatePanel(
        root,
        () => crepe.getMarkdown(),
        (markdown) => crepe.editor.action(replaceAll(markdown)),
      ),
    )
    const panel = await templatePanelPromise
    panel.open()
  })
  draftController = createLocalDraftController(
    root,
    `smart-reporting-editor:${basePath}`,
    (markdown) => crepe.editor.action(replaceAll(markdown)),
  )
  draftController.offer(documentState.markdown)
  if (metricsLabel) metricsLabel.textContent = documentMetrics(documentState.markdown)
  historyController.record(`Revision ${revision} · 初始版本`, documentState.markdown)
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
    const markdown = crepe.getMarkdown()
    currentMarkdown = markdown
    if (markdown === lastSavedMarkdown) return
    status('保存中', 'busy')
    saveState?.beginSave()
    const saveStartedAt = performance.now()
    const savingMarkdown = markdown
    savePromise = client
      .save(savingMarkdown, sha256)
      .then((saved) => {
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
      const warnings = reportPreflight(crepe.getMarkdown(), shell.editor)
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
