import '@milkdown/crepe/theme/common/prosemirror.css'
import '@milkdown/crepe/theme/common/reset.css'
import '@milkdown/crepe/theme/common/block-edit.css'
import '@milkdown/crepe/theme/common/cursor.css'
import '@milkdown/crepe/theme/common/link-tooltip.css'
import '@milkdown/crepe/theme/common/list-item.css'
import '@milkdown/crepe/theme/common/placeholder.css'
import '@milkdown/crepe/theme/common/toolbar.css'
import '@milkdown/crepe/theme/common/table.css'
import '@milkdown/crepe/theme/common/top-bar.css'
import '@milkdown/crepe/theme/common/ai.css'
import '@milkdown/crepe/theme/common/diff.css'
import '@milkdown/crepe/theme/frame.css'
import './style.css'

import { editorViewCtx } from '@milkdown/kit/core'
import { indent } from '@milkdown/kit/plugin/indent'
import { trailing } from '@milkdown/kit/plugin/trailing'
import { outline } from '@milkdown/kit/utils'
import { replaceAll } from '@milkdown/kit/utils'
import {
  createIcons,
  Database,
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
  Share2,
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
import { evidenceLocationPlugin, evidenceLocationKey, evidenceLocationTransaction, findEvidenceTableCell, findEvidenceChartImage, findProtocolMarkerElement } from './evidence-location'
import { restoreProtocolMarkers } from './protocol'
import { findDocumentMatches, replaceDocumentMatches } from './search-document'
import { searchHighlightPlugin, searchHighlightPluginKey } from './search-highlight-plugin'
import { applyLineageFeatureVisibility, createEditorShell } from './shell'
import { createOutlineController, displayOutlineText, namedOutlineItems, type OutlineItem } from './outline'
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
import { createSharePanel } from './share'
import { createSourceValidationController, sourceValidationIssueCount, markdownSha256 } from './source-validation'
import { linkedSubjectFromSearch } from './linked-subject'

const root = document.querySelector<HTMLElement>('#app')
if (!root) throw new Error('report editor root is missing')

const basePath = window.location.pathname.replace(/\/$/, '')
const parts = basePath.split('/')
const revision = parts.at(-1) ?? ''
const shell = createEditorShell(root, toolbarMode(window.innerWidth))
const appBar = root.querySelector<HTMLElement>('.app-bar')
if (appBar) {
  const syncAppBarHeight = () =>
    document.documentElement.style.setProperty('--app-bar-height', `${appBar.offsetHeight}px`)
  new ResizeObserver(syncAppBarHeight).observe(appBar)
  syncAppBarHeight()
}
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
const preferences = createEditorPreferenceController(root, basePath)
createFocusModeController(root, shell.focus, shell.focusExit)
const exportPanel = createExportPanel()
const sharePanel = createSharePanel(root, () => client.share())
shell.share.addEventListener('click', () => sharePanel.open())
// 导出阻塞遮罩（blockUI/unblockUI）：渲染与验收可持续数分钟，期间全屏禁止编辑，
// 避免用户在导出进行中改内容导致 revision 错乱。
const blockOverlay = document.createElement('div')
blockOverlay.className = 'export-block-overlay'
blockOverlay.hidden = true
blockOverlay.setAttribute('role', 'alert')
blockOverlay.setAttribute('aria-live', 'assertive')
blockOverlay.innerHTML = '<div class="export-block-card"><span class="export-block-spinner" aria-hidden="true"></span><p class="export-block-message"></p></div>'
root.append(blockOverlay)
const blockMessage = blockOverlay.querySelector<HTMLElement>('.export-block-message')!
const blockUI = (message: string) => {
  blockMessage.textContent = message
  blockOverlay.hidden = false
}
const unblockUI = () => {
  blockOverlay.hidden = true
}
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
    if (currentSectionLabel) currentSectionLabel.textContent = `当前位置：${displayOutlineText(item.text)}`
  },
})
const revisionLabel = root.querySelector<HTMLElement>('.revision-label')
const metricsLabel = root.querySelector<HTMLElement>('.doc-metrics')
const structureLabel = root.querySelector<HTMLElement>('.structure-status')
const imageQualityLabel = root.querySelector<HTMLElement>('.image-quality-status')
const sourceStatusLabel = document.createElement('span')
sourceStatusLabel.className = 'source-validation-status'
sourceStatusLabel.setAttribute('role', 'status')
sourceStatusLabel.setAttribute('aria-live', 'polite')
sourceStatusLabel.hidden = true
structureLabel?.after(sourceStatusLabel)
if (revisionLabel) revisionLabel.textContent = formatRevisionLabel(revision)
createIcons({
  icons: {
    Database,
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
    Share2,
    Settings2,
    X,
  },
})

const base = document.createElement('base')
base.href = `${basePath}/asset/`
document.head.prepend(base)

const client = new ReportEditorClient(basePath)
let lineagePanelEnabled = true
const sourceValidation = createSourceValidationController(
  client,
  () => getEditorMarkdown(),
  (result) => {
    if (!lineagePanelEnabled) return
    if (!result) {
      sourceStatusLabel.textContent = '来源暂无法校验'
      sourceStatusLabel.dataset.state = 'unknown'
    } else {
      // 表格与 claim 同为软语义：排序不失效，改值/插删行计入待复核；
      // 复制出的新格（与冻结值重复）同样提示复核，不自动赋予绑定。
      const issues = sourceValidationIssueCount(result)
      if (issues) {
        sourceStatusLabel.textContent = `来源待复核 ${issues} 处`
        sourceStatusLabel.dataset.state = 'stale'
      } else {
        const hasBindings = result.subjects.length > 0 || (result.tableSummary?.valid ?? 0) > 0 ||
          (result.charts?.some((chart) => chart.status === 'valid') ?? false)
        sourceStatusLabel.textContent = hasBindings ? '来源对应当前内容' : '当前内容无精确来源绑定'
        sourceStatusLabel.dataset.state = hasBindings ? 'valid' : 'unknown'
      }
    }
    sourceStatusLabel.hidden = false
  },
  () => {
    if (!lineagePanelEnabled) return
    sourceStatusLabel.textContent = '来源校验中'
    sourceStatusLabel.dataset.state = 'checking'
    sourceStatusLabel.hidden = false
  },
)
const scheduleSourceValidation = () => {
  if (lineagePanelEnabled) sourceValidation.schedule()
}
// B5/v6：证据浏览器——核对任务页签 + 探索路径 + 对象页，覆盖编辑器但不卸载它。
// 单独拆 chunk，避免图关系与对象详情代码增大编辑器首屏入口包。
let captureEvidenceEditor = () => {}
let restoreEvidenceEditor = () => shell.editor.focus({ preventScroll: true })
let focusEvidenceTarget = (_target: HTMLElement) => shell.editor.focus({ preventScroll: true })
let evidenceLocateIntent = 0
const { createEvidenceBrowser } = await import('./evidence-browser')
const evidenceBrowser = createEvidenceBrowser(root, {
  client,
  revisionLabel: formatRevisionLabel(revision),
  storageKey: `smart-reporting-evidence:${basePath}`,
  onOpen: () => captureEvidenceEditor(),
  onReturnToReport: () => restoreEvidenceEditor(),
  locateSubject: (subjectId) => {
    const intent = ++evidenceLocateIntent
    const reveal = (target: HTMLElement) => {
      focusEvidenceTarget(target)
      const reducedMotion = typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
      target.scrollIntoView({ block: 'center', behavior: reducedMotion ? 'auto' : 'smooth' })
    }
    const findMarker = (selector: string, kind: 'citation' | 'section', value: string) =>
      findProtocolMarkerElement(shell.editor, selector, kind, value)
    const locate = (sectionId?: string | null) => {
      const citation = findMarker('.report-citation-marker', 'citation', subjectId)
      const section = sectionId ? findMarker('.report-section-marker', 'section', sectionId) : undefined
      const marker = citation ?? section
      const target = marker?.closest<HTMLElement>('p, li, td, th, h1, h2, h3, h4') ?? marker
      if (!target) {
        shell.editor.focus({ preventScroll: true })
        status('当前正文中未找到该引用的位置，可能已被修改或删除', 'dirty')
        return
      }
      reveal(target)
    }
    const marker = findMarker('.report-citation-marker', 'citation', subjectId)
    if (marker) {
      locate()
      return
    }
    void client.sources().then(async (sources) => {
      if (intent !== evidenceLocateIntent || evidenceBrowser.isOpen()) return
      const subject = sources.subjects?.find((item) => item.subjectId === subjectId)
      if (subject?.subjectKind === 'table_cell') {
        const markdown = getEditorMarkdown()
        const digest = await markdownSha256(markdown)
        const result = await client.validateSources(markdown, digest)
        if (intent !== evidenceLocateIntent || evidenceBrowser.isOpen() || getEditorMarkdown() !== markdown) return
        const table = result.draftSha256 === digest
          ? result.tables?.find(item => item.tableId === subject.locator.tableId) : undefined
        const location = table?.locations?.find(item => item.rowKey === subject.locator.rowKey && item.columnKey === subject.locator.columnKey)
        const target = location && subject.locator.tableId
          ? findEvidenceTableCell(shell.editor, subject.locator.tableId, location) : null
        if (target) reveal(target)
        else status('当前草稿无法确认该单元格的位置，请核对表格标签', 'dirty')
        return
      }
      if (subject?.subjectKind === 'chart' || subject?.subjectKind === 'chart_caption') {
        const markdown = getEditorMarkdown()
        const digest = await markdownSha256(markdown)
        const result = await client.validateSources(markdown, digest)
        if (intent !== evidenceLocateIntent || evidenceBrowser.isOpen() || getEditorMarkdown() !== markdown) return
        const chart = result.draftSha256 === digest
          ? result.charts?.find(item => item.chartId === subject.locator.chartId) : undefined
        const target = chart?.locationSource
          ? findEvidenceChartImage(shell.editor, chart.locationSource, document.baseURI, subject.subjectKind === 'chart_caption') : null
        if (target) reveal(target)
        else status('当前草稿无法确认该图表的位置，请核对图片引用', 'dirty')
        return
      }
      locate(subject?.locator.sectionId)
    }).catch(() => {
      if (intent === evidenceLocateIntent && !evidenceBrowser.isOpen()) {
        shell.editor.focus({ preventScroll: true })
        status('正文位置暂时无法确认，请稍后重试', 'dirty')
      }
    })
  },
  getDraft: () => ({ markdown: getEditorMarkdown(), sha256 }),
})
shell.sources.addEventListener('click', () => evidenceBrowser.open())
const telemetry = createTelemetryReporter((payload) => client.reportEvent(payload))
const loadStartedAt = performance.now()
let conflictPanel: ReturnType<typeof createConflictPanel> | null = null
// 409 后远端 sha 只暂存，用户明确选择前不得采用：否则防抖中的自动保存会用远端 sha
// 提交本地内容并成功，在冲突面板仍打开时静默覆盖他人修改。
let pendingConflict: { remoteSha: string; base: string; remote: string } | null = null
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
  const named = namedOutlineItems(items)
  const chapterCount = named.filter((item) => item.level === 2).length
  outlineController.update(named, chapterCount || undefined)
  const structure = headingStructureStatus(named)
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
  lineagePanelEnabled = documentState.lineageFeatures?.panel ?? true
  applyLineageFeatureVisibility(shell, documentState.lineageFeatures)
  evidenceBrowser.setDownloadEnabled(documentState.lineageFeatures?.download ?? true)
  evidenceBrowser.setDrilldownEnabled(documentState.lineageFeatures?.drilldown ?? true)
  exportSettingsPanel.setSourcesEnabled(documentState.lineageFeatures?.exportSources ?? true)
  if (!lineagePanelEnabled) {
    sourceValidation.cancel()
    sourceStatusLabel.hidden = true
  }
  const saveInBackground = () => runInBackground(saveNow())
  void telemetry.record({
    event: 'document_loaded',
    durationMs: Math.round(performance.now() - loadStartedAt),
  })
  const acceptRemoteBase = () => {
    if (pendingConflict) sha256 = pendingConflict.remoteSha
    pendingConflict = null
  }
  conflictPanel = createConflictPanel(root, {
    keepLocal: () => {
      acceptRemoteBase()
      saveInBackground()
    },
    useRemote: () => void recoverFromConflict(),
    mergeAndRetry: (markdown) => {
      acceptRemoteBase()
      // 合并结果可能引入当前正文没有的协议标记；flush 重建 EditorState 避免被拦截。
      crepe.editor.action(replaceAll(markdown, true))
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
  crepe.editor.use(evidenceLocationPlugin)
  crepe.editor.use(searchHighlightPlugin)
  crepe.editor.use(indent)
  crepe.editor.use(trailing)
  getEditorMarkdown = () => restoreProtocolMarkers(crepe.getMarkdown())
  await crepe.create()
  const evidenceView = crepe.editor.action((ctx) => ctx.get(editorViewCtx))
  let evidenceLocationTimer: number | undefined
  focusEvidenceTarget = (target) => {
    window.clearTimeout(evidenceLocationTimer)
    evidenceView.dispatch(evidenceLocationTransaction(evidenceView.state, evidenceView.posAtDOM(target, 0)))
    evidenceView.focus()
    evidenceLocationTimer = window.setTimeout(() => {
      evidenceView.dispatch(evidenceView.state.tr.setMeta(evidenceLocationKey, null).setMeta('addToHistory', false))
    }, 1800)
  }
  let evidenceScene: {
    doc: typeof evidenceView.state.doc
    selection: ReturnType<typeof evidenceView.state.selection.getBookmark>
    left: number
    top: number
  } | null = null
  captureEvidenceEditor = () => {
    evidenceScene = {
      doc: evidenceView.state.doc,
      selection: evidenceView.state.selection.getBookmark(),
      left: window.scrollX,
      top: window.scrollY,
    }
  }
  restoreEvidenceEditor = () => {
    const scene = evidenceScene
    evidenceScene = null
    // 修订恢复或正文替换后不把旧选区套到新文档上。
    if (scene && evidenceView.state.doc === scene.doc) {
      evidenceView.dispatch(evidenceView.state.tr.setSelection(scene.selection.resolve(evidenceView.state.doc)))
    }
    evidenceView.focus()
    if (scene && evidenceView.state.doc === scene.doc) window.scrollTo({ left: scene.left, top: scene.top, behavior: 'auto' })
  }
  const { installSlashMenuHeadingPreview } = await import('./slash-menu-preview')
  installSlashMenuHeadingPreview()
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
      scheduleSourceValidation()
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
    void createInteractiveCharts(shell.editor, documentState.interactiveCharts, basePath, {
      theme: documentState.visualTheme,
    }).refresh()
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
    async (markdown, historyRevision) => {
      if (historyRevision === undefined) {
        // 会话快照可能包含当前正文没有的协议标记；flush 重建 EditorState 避免被拦截。
        crepe.editor.action(replaceAll(markdown, true))
        status('会话快照已恢复为草稿', 'dirty')
        return
      }
      setActionsDisabled(true)
      blockUI('正在恢复历史版本及来源')
      try {
        await saveNow()
        sourceValidation.cancel()
        const restored = await client.restoreHistory(historyRevision, sha256)
        sha256 = restored.sha256
        lastSavedMarkdown = restored.markdown
        currentMarkdown = restored.markdown
        saveState?.reset(restored.markdown)
        draftController?.clear()
        evidenceBrowser.reset()
        // 历史版本可能包含当前正文没有的协议标记；flush 重建 EditorState，避免
        // protocolMarkerPlugin 的 filterTransaction 把整笔替换拦截掉。
        crepe.editor.action(replaceAll(restored.markdown, true))
        window.clearTimeout(saveTimer)
        scheduleSourceValidation()
        status(`已恢复第 ${restored.sourceRevision ?? historyRevision} 版及来源`)
      } catch (error) {
        scheduleSourceValidation()
        status(errorStatusLabel(error), 'error')
        throw error
      } finally {
        unblockUI()
        setActionsDisabled(false)
      }
    },
    async (historyRevision) => (await client.historyRevision(historyRevision)).markdown,
    createPersistedHistoryLoader((limit, offset) => client.historyPage(limit, offset)),
  )
  shell.history.addEventListener('click', () => historyController.open())
  draftController = createLocalDraftController(
    root,
    `smart-reporting-editor:${basePath}`,
    // 本地草稿可能包含当前正文没有的协议标记；flush 重建 EditorState 避免被拦截。
    (markdown) => crepe.editor.action(replaceAll(markdown, true)),
  )
  draftController.offer(documentState.markdown)
  initialFormalHeadings = formalHeadings(documentState.markdown)
  if (metricsLabel) metricsLabel.textContent = documentMetrics(documentState.markdown)
  historyController.record(`${formatRevisionLabel(revision)} · 初始版本`, documentState.markdown)
  createImagePreview(shell.editor)
  updateOutline(crepe.editor.action(outline()))
  scheduleSourceValidation()
  const linkedSubject = linkedSubjectFromSearch(window.location.search)
  if (lineagePanelEnabled && linkedSubject) void evidenceBrowser.openSubject(linkedSubject)
  status(savedLabel())
  const saveScroll = () => preferences.saveScroll(window.scrollY)
  window.addEventListener('scroll', saveScroll, { passive: true })
  preferences.restoreScroll()

  const reopenConflict = () => {
    if (pendingConflict) {
      conflictPanel?.show(pendingConflict.base, getEditorMarkdown(), pendingConflict.remote)
    }
  }
  const showConflictStatus = () =>
    status('保存冲突 · 请选择本地或远端版本', 'error', reopenConflict)

  async function saveNow(): Promise<void> {
    window.clearTimeout(saveTimer)
    if (pendingConflict) {
      // 冲突未决时暂停所有保存（含自动保存与导出前保存），等待用户选择。
      showConflictStatus()
      throw new ReportEditorApiError(409, 'report_editor_conflict')
    }
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
            pendingConflict = {
              remoteSha: remote.sha256,
              base: lastSavedMarkdown,
              remote: remote.markdown,
            }
            conflictPanel?.show(lastSavedMarkdown, savingMarkdown, remote.markdown)
            showConflictStatus()
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
      pendingConflict = null
      // 远端版本可能包含当前正文没有的协议标记；flush 重建 EditorState 避免被拦截。
      crepe.editor.action(replaceAll(latest.markdown, true))
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
      blockUI(`正在生成 ${formatLabel}，渲染与验收可能需要几分钟，期间请勿关闭页面…`)
      const { note = '', ...settings } = pendingExportSettings ?? {
        cover: false,
        toc: true,
        headerFooter: true,
        pageNumbers: true,
        sources: true,
        note: '',
      }
      const result = await client.export(sha256, settings, note)
      unblockUI()
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
      unblockUI()
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
