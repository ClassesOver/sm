import { ReportEditorApiError, type ReportEditorClient, type TraceSources } from './api'
import {
  createEvidenceState,
  evidenceRefId,
  REPORT_TAB,
  type EvidenceObjectKind,
  type EvidenceObjectRef,
  type EvidencePage,
  type EvidenceStore,
  type EvidenceTask,
} from './evidence-state'
import { appendHighlighted, renderEvidencePage } from './evidence-pages'
import { EVIDENCE_KIND_COLORS, EVIDENCE_KIND_ICONS, subjectLabel } from './evidence-relations'
import { createEvidenceGraph, type EvidenceGraph } from './evidence-graph'
import { ArrowLeft, ArrowRight, createElement, FileText, MoreHorizontal, RotateCcw, X } from 'lucide'

/**
 * 证据浏览器外壳（证据浏览器 v6）：任务页签 + 探索面包屑 + 来源目录 + 对象页。
 *
 * 与编辑器共存：浏览器是覆盖在编辑器之上的全屏视图，编辑器实例从不卸载，
 * 「报告正文」页签/返回正文只是隐藏本视图，滚动与未保存状态天然保留。
 *
 * 入口行为（设计稿「入口行为统一」）：
 * - 正文引用 openSubject / 目录 / 目录搜索：开启或激活独立核对任务；
 * - 对象页与图内的关系入口：当前任务内导航（由 evidence-pages 经 ctx 调用）；
 * - Ctrl/⌘ + 单击或中键：后台开启独立任务，不抢焦点。
 */

export const EVIDENCE_KIND_LABELS: Record<EvidenceObjectKind, string> = {
  fact: '事实',
  computation: '计算',
  dataset: '快照',
  chart: '图表',
  subject: '引用',
}

export interface EvidenceBrowserOptions {
  client: ReportEditorClient
  revisionLabel: string
  storageKey?: string
  /** 隐藏浏览器、回到编辑器（「返回正文」）。 */
  onReturnToReport: () => void
  onOpen?: () => void
  /** 定位正文中的引用锚点。 */
  locateSubject: (subjectId: string) => void
  /** 当前草稿（引用状态校验用）。 */
  getDraft?: () => { markdown: string; sha256: string } | null
  downloadEnabled?: boolean
  drilldownEnabled?: boolean
}

const SOURCE_UNAVAILABLE_LABELS: Record<string, string> = {
  source_index_missing: '当前修订没有来源索引（旧报告或来源未登记）',
  feature_disabled: '来源追溯功能未启用',
  snapshot_expired: '数据快照已超过保留期，登记信息仍可查看，明细不可用',
}

export function createEvidenceBrowser(root: HTMLElement, options: EvidenceBrowserOptions) {
  const storageKey = options.storageKey ?? 'smart-reporting-evidence-session'
  const loadStore = (): EvidenceStore | undefined => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      if (!raw) return undefined
      const parsed = JSON.parse(raw) as EvidenceStore
      if (!parsed || !Array.isArray(parsed.tasks) || typeof parsed.active !== 'string') return undefined
      // 空历史或越界的 index 会让 currentPage() 取到 undefined；损坏/旧版数据一律丢弃或收敛到有效范围。
      parsed.tasks = parsed.tasks.filter((task) =>
        task && typeof task.key === 'string' && task.root && Array.isArray(task.history) &&
        task.history.length > 0 &&
        task.history.every((page) => page && page.ref && Array.isArray(page.path)),
      )
      for (const task of parsed.tasks) {
        task.index = Number.isInteger(task.index)
          ? Math.max(0, Math.min(task.index, task.history.length - 1)) : task.history.length - 1
        task.used = Number.isFinite(task.used) ? task.used : 0
        for (const page of task.history) {
          page.selected ??= null
          page.collapsed ??= false
          page.showList ??= false
          page.graphView ??= false
          page.filter ??= ''
          if (!Array.isArray(page.datasetCursors) || !page.datasetCursors.length ||
              !page.datasetCursors.every((cursor) => cursor === null || typeof cursor === 'string')) {
            page.datasetCursors = [null]
          }
          page.datasetPageIndex = Number.isInteger(page.datasetPageIndex)
            ? Math.max(0, Math.min(page.datasetPageIndex, page.datasetCursors.length - 1)) : 0
          if (page.datasetColumnWindow !== undefined &&
              !(Number.isInteger(page.datasetColumnWindow) && page.datasetColumnWindow >= 0)) {
            delete page.datasetColumnWindow
          }
          page.chartOffset = Number.isInteger(page.chartOffset) && page.chartOffset >= 0 ? page.chartOffset : 0
          page.columnWidths ??= {}
          page.tableScroll ??= 0
          page.scroll ??= 0
          page.graphScroll ??= { left: 0, top: 0 }
          page.graphScale ??= 1
          page.graphPan ??= { x: 0, y: 0 }
        }
      }
      if (parsed.active !== REPORT_TAB && !parsed.tasks.some((task) => task.key === parsed.active)) {
        parsed.active = REPORT_TAB
      }
      return parsed
    } catch {
      return undefined
    }
  }
  const state = createEvidenceState(loadStore())
  const persist = () => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(state.store))
    } catch {
      // 隐私模式或存储配额不足时，当前页仍可正常使用。
    }
  }
  let isOpen = false
  let downloadEnabled = options.downloadEnabled ?? true
  let drilldownEnabled = options.drilldownEnabled ?? true
  let pageController: AbortController | null = null
  let renderingWorkspace = false
  let sourcesPromise: Promise<TraceSources> | null = null
  let sourcesController: AbortController | null = null
  let directoryController: AbortController | null = null
  let navigationIntent = 0
  let directoryRefs: EvidenceObjectRef[] = []
  /** 目录说明：来源不可用的原因，或部分目录加载失败（可重试）。 */
  let directoryNotes: { text: string; retry?: boolean }[] = []
  let directoryFilter = ''
  const pageDataCache = new WeakMap<EvidencePage, unknown>()
  const taskGraphs = new WeakMap<EvidenceTask, EvidenceGraph>()

  const shell = document.createElement('div')
  shell.className = 'evidence-shell'
  shell.hidden = true
  shell.innerHTML = `
    <div class="evidence-tabs-line">
      <div class="evidence-tabs" role="tablist" aria-label="核对任务"></div>
      <details class="evidence-task-picker">
        <summary aria-label="全部任务">全部任务</summary>
        <div class="evidence-popup evidence-task-items" aria-label="全部核对任务"></div>
      </details>
      <button type="button" class="ui-button evidence-directory-toggle"
        aria-expanded="false" aria-controls="evidence-directory">来源目录</button>
    </div>
    <div class="evidence-nav">
      <button type="button" class="evidence-nav-arrow" data-evidence="back" aria-label="后退" title="后退"></button>
      <button type="button" class="evidence-nav-arrow" data-evidence="forward" aria-label="前进" title="前进"></button>
      <span class="evidence-nav-label">探索路径</span>
      <nav class="evidence-crumbs" aria-label="探索路径"></nav>
      <details class="evidence-path-picker">
        <summary aria-label="完整探索路径" title="完整探索路径"></summary>
        <div class="evidence-popup evidence-path-items" aria-label="完整探索路径"></div>
      </details>
      <span class="evidence-revision"></span>
    </div>
    <p class="evidence-notice" role="status" hidden></p>
    <div class="evidence-body">
      <aside class="evidence-directory" id="evidence-directory" aria-label="来源目录">
        <div class="evidence-directory-head"></div>
        <input type="search" class="evidence-directory-search" placeholder="搜索来源目录"
          aria-label="搜索来源目录" />
        <div class="evidence-directory-items"></div>
        <p class="evidence-directory-note">目录与搜索会开启独立核对任务，不覆盖当前任务的导航历史。</p>
      </aside>
      <div class="evidence-directory-scrim" hidden></div>
      <main class="evidence-workspace" tabindex="-1" aria-label="证据对象"></main>
    </div>
    <div class="evidence-announcer sr-only" aria-live="polite"></div>`
  root.append(shell)
  shell.querySelector<HTMLButtonElement>('[data-evidence="back"]')?.append(
    createElement(ArrowLeft, { width: 16, height: 16, 'aria-hidden': 'true' }),
  )
  shell.querySelector<HTMLButtonElement>('[data-evidence="forward"]')?.append(
    createElement(ArrowRight, { width: 16, height: 16, 'aria-hidden': 'true' }),
  )
  const pathPickerSummary = shell.querySelector<HTMLElement>('.evidence-path-picker summary')
  if (pathPickerSummary) {
    pathPickerSummary.replaceChildren(createElement(MoreHorizontal, { width: 16, height: 16, 'aria-hidden': 'true' }))
  }

  const taskPicker = shell.querySelector<HTMLDetailsElement>('.evidence-task-picker')!
  const taskItems = shell.querySelector<HTMLElement>('.evidence-task-items')!
  const pathPicker = shell.querySelector<HTMLDetailsElement>('.evidence-path-picker')!
  const pathItems = shell.querySelector<HTMLElement>('.evidence-path-items')!
  const tabList = shell.querySelector<HTMLElement>('.evidence-tabs')!
  const directoryToggle = shell.querySelector<HTMLButtonElement>('.evidence-directory-toggle')!
  const directory = shell.querySelector<HTMLElement>('.evidence-directory')!
  const directoryHead = shell.querySelector<HTMLElement>('.evidence-directory-head')!
  const directorySearch = shell.querySelector<HTMLInputElement>('.evidence-directory-search')!
  const directoryItems = shell.querySelector<HTMLElement>('.evidence-directory-items')!
  const workspace = shell.querySelector<HTMLElement>('.evidence-workspace')!
  workspace.id = 'evidence-workspace'
  workspace.setAttribute('role', 'tabpanel')
  const backButton = shell.querySelector<HTMLButtonElement>('[data-evidence="back"]')!
  const forwardButton = shell.querySelector<HTMLButtonElement>('[data-evidence="forward"]')!
  const crumbs = shell.querySelector<HTMLElement>('.evidence-crumbs')!
  const revisionBadge = shell.querySelector<HTMLElement>('.evidence-revision')!
  const announcer = shell.querySelector<HTMLElement>('.evidence-announcer')!

  revisionBadge.textContent = options.revisionLabel
  directoryHead.textContent = `来源目录 · ${options.revisionLabel}`

  const announce = (message: string) => {
    announcer.textContent = ''
    announcer.textContent = message
  }

  const popupIcon = (icon: SVGElement): SVGElement => {
    icon.classList.add('evidence-popup-icon')
    return icon
  }

  const closePickers = () => {
    taskPicker.open = false
    pathPicker.open = false
  }
  shell.addEventListener('pointerdown', (event) => {
    for (const picker of [taskPicker, pathPicker]) {
      if (!picker.contains(event.target as Node)) picker.open = false
    }
  })
  shell.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return
    const picker = [taskPicker, pathPicker].find((item) => item.open)
    if (!picker) return
    event.preventDefault()
    picker.open = false
    picker.querySelector<HTMLElement>('summary')!.focus()
  })

  // ------------------------------------------------------------------
  // 页签栏：固定「报告正文」+ 任务页签（手动激活，W3C Tabs Pattern）
  // ------------------------------------------------------------------

  const taskPageKind = (task: EvidenceTask): EvidenceObjectKind =>
    task.history[task.index].ref.kind

  const activateTab = (key: string) => {
    if (key === REPORT_TAB) {
      hideShell()
      return
    }
    state.switchTask(key)
    renderAll()
    announce(`已切换到核对任务 ${state.currentTask()?.root.label ?? ''}`)
  }

  const closeTab = (key: string) => {
    const wasActive = state.store.active === key
    state.closeTask(key)
    if (state.store.active === REPORT_TAB) {
      hideShell()
      return
    }
    renderAll()
    if (wasActive) announce(`已切换到核对任务 ${state.currentTask()?.root.label ?? ''}`)
  }

  // 页签多于可见宽度时，当前页签可能停在滚动区域之外；只在页签栏内水平滚动，
  // 不使用 scrollIntoView，避免带动整页或编辑器纵向滚动。
  const revealActiveTab = () => {
    const tab = tabList.querySelector<HTMLElement>('.evidence-tab[aria-selected="true"]')
    const target = tab?.closest<HTMLElement>('.evidence-tab-wrap') ?? tab
    if (!target || tabList.scrollWidth <= tabList.clientWidth) return
    const listRect = tabList.getBoundingClientRect()
    const rect = target.getBoundingClientRect()
    if (rect.left < listRect.left) tabList.scrollLeft -= listRect.left - rect.left + 8
    else if (rect.right > listRect.right) tabList.scrollLeft += rect.right - listRect.right + 8
  }

  const renderTabs = () => {
    // 重新渲染会销毁焦点元素；记录并按身份恢复，避免键盘操作后失位。
    const focusedKey = tabList.contains(document.activeElement)
      ? (document.activeElement as HTMLElement).dataset?.evidenceTab
      : undefined
    tabList.innerHTML = ''
    taskItems.innerHTML = ''
    taskPicker.open = false
    const reportTab = document.createElement('button')
    reportTab.type = 'button'
    reportTab.role = 'tab'
    reportTab.className = 'evidence-tab evidence-tab-report'
    reportTab.dataset.evidenceTab = REPORT_TAB
    reportTab.id = 'evidence-tab-report'
    reportTab.setAttribute('aria-controls', workspace.id)
    reportTab.textContent = '报告正文'
    reportTab.title = '返回正文，编辑器状态保持不变'
    reportTab.setAttribute('aria-selected', String(!isOpen))
    reportTab.tabIndex = isOpen ? -1 : 0
    reportTab.addEventListener('click', () => activateTab(REPORT_TAB))
    tabList.append(reportTab)
    const reportItem = document.createElement('button')
    reportItem.type = 'button'
    reportItem.textContent = '报告正文'
    reportItem.prepend(popupIcon(createElement(FileText, { width: 15, height: 15, 'aria-hidden': 'true' })))
    if (!isOpen) reportItem.setAttribute('aria-current', 'true')
    reportItem.addEventListener('click', () => activateTab(REPORT_TAB))
    taskItems.append(reportItem)
    // “恢复”是操作而非任务：放在任务清单之后、以分隔线隔开。
    const restore = document.createElement('button')
    restore.type = 'button'
    restore.className = 'evidence-popup-action'
    restore.textContent = '恢复最近关闭的任务'
    restore.prepend(popupIcon(createElement(RotateCcw, { width: 15, height: 15, 'aria-hidden': 'true' })))
    restore.disabled = state.closedTasks.length === 0
    restore.addEventListener('click', () => {
      const task = state.restoreTask()
      if (!task) return
      renderAll()
      announce(`已恢复核对任务 ${task.root.label}`)
    })
    for (const task of state.store.tasks) {
      const wrap = document.createElement('span')
      wrap.className = 'evidence-tab-wrap'
      const tab = document.createElement('button')
      tab.type = 'button'
      tab.role = 'tab'
      tab.className = 'evidence-tab'
      tab.dataset.evidenceTab = task.key
      tab.id = `evidence-tab-${task.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`
      tab.setAttribute('aria-controls', workspace.id)
      tab.setAttribute('aria-selected', String(isOpen && state.store.active === task.key))
      tab.tabIndex = isOpen && state.store.active === task.key ? 0 : -1
      tab.draggable = true
      tab.addEventListener('dragstart', (event) => {
        event.dataTransfer?.setData('text/plain', task.key)
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
      })
      tab.addEventListener('dragover', (event) => {
        event.preventDefault()
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
      })
      tab.addEventListener('drop', (event) => {
        event.preventDefault()
        const source = event.dataTransfer?.getData('text/plain')
        if (!source || source === task.key) return
        const targetIndex = state.store.tasks.findIndex((item) => item.key === task.key)
        state.reorderTask(source, targetIndex)
        renderTabs()
        persist()
      })
      const name = document.createElement('span')
      name.className = 'evidence-tab-name'
      name.textContent = task.root.label
      const stage = document.createElement('span')
      stage.className = 'evidence-tab-stage'
      stage.textContent = EVIDENCE_KIND_LABELS[taskPageKind(task)]
      tab.append(name, stage)
      const currentPath = task.history[task.index].path.map((ref) => ref.label).join(' / ')
      tab.title = currentPath
      const close = document.createElement('button')
      close.type = 'button'
      close.className = 'evidence-tab-close'
      close.setAttribute('aria-label', `关闭核对任务 ${task.root.label}`)
      close.append(createElement(X, { width: 14, height: 14, 'aria-hidden': 'true' }))
      close.addEventListener('click', (event) => {
        event.stopPropagation()
        closeTab(task.key)
      })
      tab.addEventListener('click', () => activateTab(task.key))
      wrap.append(tab, close)
      tabList.append(wrap)
      const item = document.createElement('button')
      item.type = 'button'
      item.textContent = `${task.root.label} · ${EVIDENCE_KIND_LABELS[taskPageKind(task)]}`
      item.prepend(popupIcon(createElement(EVIDENCE_KIND_ICONS[task.root.kind], {
        width: 15, height: 15, 'aria-hidden': 'true', color: EVIDENCE_KIND_COLORS[task.root.kind],
      })))
      item.title = currentPath
      if (isOpen && state.store.active === task.key) item.setAttribute('aria-current', 'true')
      item.addEventListener('click', () => activateTab(task.key))
      taskItems.append(item)
    }
    taskItems.append(restore)
    const activeTabId = isOpen && state.store.active
      ? `evidence-tab-${state.store.active.replace(/[^a-zA-Z0-9_-]/g, '-')}`
      : 'evidence-tab-report'
    workspace.setAttribute('aria-labelledby', activeTabId)
    revealActiveTab()
    if (focusedKey) {
      tabList.querySelector<HTMLButtonElement>(`[data-evidence-tab="${focusedKey}"]`)?.focus()
    }
  }

  // 手动激活：方向键只移动焦点，Enter/Space 才激活；Delete 关闭证据页签。
  tabList.addEventListener('keydown', (event) => {
    const tabs = [...tabList.querySelectorAll<HTMLButtonElement>('.evidence-tab')]
    const focused = tabs.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault()
      const delta = event.key === 'ArrowLeft' ? -1 : 1
      tabs[(focused + delta + tabs.length) % tabs.length]?.focus()
      return
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      tabs[event.key === 'Home' ? 0 : tabs.length - 1]?.focus()
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      const key = (document.activeElement as HTMLElement | null)?.dataset?.evidenceTab
      if (key) {
        event.preventDefault()
        activateTab(key)
      }
      return
    }
    if (event.key === 'Delete' && focused > 0) {
      event.preventDefault()
      const key = tabs[focused].dataset.evidenceTab
      if (key) closeTab(key)
    }
  })

  // ------------------------------------------------------------------
  // 导航栏：后退/前进 + 探索路径面包屑
  // ------------------------------------------------------------------

  const renderNav = () => {
    const task = state.currentTask()
    backButton.disabled = !task || task.index <= 0
    forwardButton.disabled = !task || task.index >= task.history.length - 1
    crumbs.innerHTML = ''
    pathItems.innerHTML = ''
    pathPicker.open = false
    pathPicker.hidden = !task || task.history[task.index].path.length < 2
    if (!task) {
      const editing = document.createElement('span')
      editing.className = 'evidence-crumb-current'
      editing.textContent = '未打开核对任务'
      crumbs.append(editing)
      return
    }
    const page = task.history[task.index]
    page.path.forEach((ref, index) => {
      const current = index === page.path.length - 1
      const step = document.createElement('span')
      step.className = 'evidence-crumb-step'
      if (index > 0 && !current) step.classList.add('evidence-crumb-middle')
      if (page.path.length > 4 && index > 0 && index < page.path.length - 2) {
        step.classList.add('evidence-crumb-folded')
      }
      if (index > 0) {
        const separator = document.createElement('span')
        separator.className = 'evidence-crumb-separator'
        separator.textContent = '/'
        step.append(separator)
      }
      const enter = () => {
        closePickers()
        state.navigate(ref)
        renderAll()
        announce(`已返回 ${ref.label}`)
      }
      const crumb = document.createElement(current ? 'span' : 'button')
      crumb.className = current ? 'evidence-crumb-current' : 'evidence-crumb'
      crumb.textContent = ref.label
      crumb.title = ref.label
      if (current) crumb.setAttribute('aria-current', 'page')
      else {
        ;(crumb as HTMLButtonElement).type = 'button'
        crumb.addEventListener('click', enter)
      }
      step.append(crumb)
      crumbs.append(step)
      const item = document.createElement('button')
      item.type = 'button'
      item.textContent = `${index + 1}. ${ref.label} · ${EVIDENCE_KIND_LABELS[ref.kind]}`
      if (current) {
        item.setAttribute('aria-current', 'page')
        item.disabled = true
      } else item.addEventListener('click', enter)
      pathItems.append(item)
    })
  }

  backButton.addEventListener('click', () => {
    if (state.back()) {
      renderAll()
      announce(`已后退到 ${state.currentPage()?.ref.label ?? ''}`)
    }
  })
  forwardButton.addEventListener('click', () => {
    if (state.forward()) {
      renderAll()
      announce(`已前进到 ${state.currentPage()?.ref.label ?? ''}`)
    }
  })

  // ------------------------------------------------------------------
  // 来源目录：目录项开启独立核对任务；搜索只过滤目录展示
  // ------------------------------------------------------------------

  const loadSources = (): Promise<TraceSources> => {
    if (!sourcesPromise) {
      sourcesController = new AbortController()
      const request = options.client.sources(sourcesController.signal).catch((error) => {
        if (sourcesPromise === request) sourcesPromise = null
        throw error
      })
      sourcesPromise = request
    }
    return sourcesPromise
  }

  const renderDirectoryNotes = () => {
    for (const note of directoryNotes) {
      const p = document.createElement('p')
      p.className = 'evidence-directory-notice'
      p.setAttribute('role', 'status')
      p.textContent = note.text
      if (note.retry) {
        const retry = document.createElement('button')
        retry.type = 'button'
        retry.className = 'evidence-directory-retry'
        retry.textContent = '重试'
        retry.addEventListener('click', () => void loadDirectory())
        p.append(' ', retry)
      }
      directoryItems.append(p)
    }
  }

  const renderDirectoryItems = () => {
    directoryItems.innerHTML = ''
    renderDirectoryNotes()
    const current = state.currentPage()
    const filter = directoryFilter.trim().toLowerCase()
    const groups: { label: string; items: EvidenceObjectRef[] }[] = []
    // 显示名已换成登记名（如方法名、文件名），页面副标题仍显示对象 ID；搜索同时匹配二者。
    const matchesId = (ref: EvidenceObjectRef) => ref.key.toLowerCase().includes(filter)
    for (const ref of directoryRefs) {
      if (filter && !ref.label.toLowerCase().includes(filter) && !matchesId(ref)) continue
      const group = groups.find((item) => item.label === EVIDENCE_KIND_LABELS[ref.kind])
      if (group) group.items.push(ref)
      else groups.push({ label: EVIDENCE_KIND_LABELS[ref.kind], items: [ref] })
    }
    if (!groups.length) {
      const empty = document.createElement('p')
      empty.className = 'evidence-directory-empty'
      empty.textContent = filter ? '目录中没有匹配的条目' : '当前修订没有登记来源'
      // 已有原因说明（如未生成来源索引）时不再追加笼统的“没有登记来源”。
      if (filter || !directoryNotes.length) directoryItems.append(empty)
      return
    }
    for (const group of groups) {
      const label = document.createElement('p')
      label.className = 'evidence-directory-group'
      label.textContent = group.label
      const count = document.createElement('span')
      count.className = 'evidence-directory-count'
      count.textContent = String(group.items.length)
      count.setAttribute('aria-label', `${group.items.length} 项`)
      label.append(count)
      directoryItems.append(label)
      for (const ref of group.items) {
        const item = document.createElement('button')
        item.type = 'button'
        item.className = 'evidence-directory-item'
        item.classList.toggle('is-current', current !== null && evidenceRefId(current.ref) === evidenceRefId(ref))
        const icon = createElement(EVIDENCE_KIND_ICONS[ref.kind], {
          width: 15, height: 15, 'aria-hidden': 'true', color: EVIDENCE_KIND_COLORS[ref.kind],
        })
        icon.classList.add('evidence-directory-icon')
        const name = document.createElement('span')
        name.className = 'evidence-directory-label'
        appendHighlighted(name, ref.label, filter)
        item.append(icon, name)
        if (filter && !ref.label.toLowerCase().includes(filter) && matchesId(ref)) {
          // 仅按 ID 命中时显示命中的 ID，说明该条目为何出现在结果中。
          const id = document.createElement('span')
          id.className = 'evidence-directory-id'
          appendHighlighted(id, ref.key, filter)
          item.append(id)
        }
        item.title = `${group.label} · ${ref.label}`
        item.addEventListener('click', () => openTaskFromDirectory(ref))
        directoryItems.append(item)
      }
    }
  }

  // 起始页概览：按类型汇总本修订已登记的来源，每类列出前几项作为快捷入口。
  // 数据只取自已加载的来源目录，不额外请求，也不推断未登记对象。
  const START_SUMMARY_LIMIT = 3
  const renderStartSummary = () => {
    const summary = workspace.querySelector<HTMLElement>('.evidence-start-summary')
    if (!summary) return
    summary.replaceChildren()
    const order: EvidenceObjectKind[] = ['dataset', 'computation', 'chart', 'fact', 'subject']
    for (const kind of order) {
      const refs = directoryRefs.filter((ref) => ref.kind === kind)
      if (!refs.length) continue
      const card = document.createElement('section')
      card.className = 'evidence-start-card'
      card.dataset.kind = kind
      const head = document.createElement('h2')
      head.className = 'evidence-start-card-head'
      head.append(createElement(EVIDENCE_KIND_ICONS[kind], {
        width: 16, height: 16, 'aria-hidden': 'true', color: EVIDENCE_KIND_COLORS[kind],
      }))
      const label = document.createElement('span')
      label.textContent = EVIDENCE_KIND_LABELS[kind]
      const count = document.createElement('span')
      count.className = 'evidence-start-count'
      count.textContent = `${refs.length} 项`
      head.append(label, count)
      const list = document.createElement('ul')
      for (const ref of refs.slice(0, START_SUMMARY_LIMIT)) {
        const item = document.createElement('li')
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'evidence-start-item'
        button.textContent = ref.label
        button.title = ref.label
        button.addEventListener('click', () => openTaskFromDirectory(ref))
        item.append(button)
        list.append(item)
      }
      card.append(head, list)
      if (refs.length > START_SUMMARY_LIMIT) {
        const more = document.createElement('p')
        more.className = 'evidence-start-more'
        more.textContent = `另有 ${refs.length - START_SUMMARY_LIMIT} 项，可在来源目录中查看`
        card.append(more)
      }
      summary.append(card)
    }
    // 没有可列出的来源时，起始页同样说明原因，而不是只留下“从目录选择”的引导。
    if (!summary.children.length) {
      for (const note of directoryNotes) {
        const p = document.createElement('p')
        p.className = 'evidence-start-notice'
        p.textContent = note.text
        summary.append(p)
      }
    }
  }

  const openTaskFromDirectory = (ref: EvidenceObjectRef) => {
    const task = state.openTask(ref, { foreground: true })
    renderAll()
    announce(`已开启核对任务 ${task.root.label}`)
    if (window.innerWidth <= 1100) setDirectoryOpen(false)
  }

  const loadDirectory = async () => {
    directoryController?.abort()
    const controller = new AbortController()
    directoryController = controller
    const stale = () => !isOpen || controller.signal.aborted || directoryController !== controller
    try {
      // 计算/图表清单请求失败与“未登记”不同：失败时如实说明并可重试，不当作没有该类来源。
      const failed = { available: false, failed: true } as const
      const [sources, computations, charts] = await Promise.all([
        loadSources(),
        options.client.computations(controller.signal).catch(() => failed),
        options.client.charts(controller.signal).catch(() => failed),
      ])
      if (stale()) return
      const notes: { text: string; retry?: boolean }[] = []
      if (!sources.available) notes.push({ text: SOURCE_UNAVAILABLE_LABELS[sources.reason ?? ''] ?? '当前修订的来源暂不可用' })
      const failedKinds = [computations === failed ? '计算记录' : '', charts === failed ? '图表' : ''].filter(Boolean)
      if (failedKinds.length) notes.push({ text: `${failedKinds.join('、')}目录加载失败，未列出的不代表没有登记。`, retry: true })
      directoryNotes = notes
      const refs: EvidenceObjectRef[] = []
      for (const dataset of sources.datasets ?? []) {
        refs.push({
          kind: 'dataset',
          key: dataset.datasetId,
          label: dataset.filename ?? dataset.businessLabel ?? dataset.datasetId,
        })
      }
      if (computations.available) {
        for (const computation of computations.computations ?? []) {
          refs.push({
            kind: 'computation',
            key: computation.computationId,
            label: computation.method || computation.computationId,
          })
        }
      }
      if (charts.available) {
        for (const chart of charts.charts ?? []) {
          refs.push({ kind: 'chart', key: chart.chartId, label: chart.chartId })
        }
      }
      for (const subject of sources.subjects ?? []) {
        refs.push({
          kind: 'subject',
          key: subject.subjectId,
          label: subjectLabel(subject.subjectId),
        })
      }
      directoryRefs = refs
      renderDirectoryItems()
      renderStartSummary()
      const labels = new Map(refs.map((ref) => [evidenceRefId(ref), ref.label]))
      if (state.relabel((ref) => labels.get(evidenceRefId(ref)))) {
        persist()
        renderTabs()
        renderNav()
        const current = state.currentPage()
        const title = workspace.querySelector<HTMLElement>('.evidence-object-title')
        if (current && title && title.textContent !== current.ref.label) title.textContent = current.ref.label
      }
    } catch {
      if (stale()) return
      directoryItems.innerHTML = ''
      const failure = document.createElement('p')
      failure.className = 'evidence-directory-empty'
      failure.textContent = '来源目录加载失败'
      const retry = document.createElement('button')
      retry.type = 'button'
      retry.className = 'ui-button'
      retry.textContent = '重试'
      retry.addEventListener('click', () => void loadDirectory())
      directoryItems.append(failure, retry)
    }
  }

  directorySearch.addEventListener('input', () => {
    directoryFilter = directorySearch.value
    renderDirectoryItems()
  })

  // 窄屏目录是覆盖在工作区上的抽屉：遮罩提示层级，点遮罩或在目录内按 Esc 关闭并归还焦点。
  const directoryScrim = shell.querySelector<HTMLElement>('.evidence-directory-scrim')!
  const setDirectoryOpen = (open: boolean) => {
    directory.classList.toggle('is-open', open)
    directoryScrim.hidden = !open
    directoryToggle.setAttribute('aria-expanded', String(open))
  }
  directoryToggle.addEventListener('click', () =>
    setDirectoryOpen(!directory.classList.contains('is-open')),
  )
  directoryScrim.addEventListener('click', () => {
    setDirectoryOpen(false)
    directoryToggle.focus({ preventScroll: true })
  })
  directory.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !directory.classList.contains('is-open')) return
    event.stopPropagation()
    setDirectoryOpen(false)
    directoryToggle.focus({ preventScroll: true })
  })

  // ------------------------------------------------------------------
  // 工作区：渲染当前任务当前页，页级请求作废与数据缓存
  // ------------------------------------------------------------------

  workspace.addEventListener(
    'scroll',
    () => {
      const page = state.currentPage()
      if (page && isOpen && !renderingWorkspace) {
        page.scroll = workspace.scrollTop
        persist()
      }
    },
    { passive: true },
  )

  const renderWorkspace = (focusNode?: EvidenceObjectRef, graphScroll?: number) => {
    pageController?.abort()
    renderingWorkspace = true
    workspace.innerHTML = ''
    const page = state.currentPage()
    if (!page) {
      const start = document.createElement('div')
      start.className = 'evidence-start'
      start.innerHTML = '<h1 class="evidence-object-title" tabindex="-1">证据浏览器</h1><p></p>'
      start.querySelector('p')!.textContent =
        '从左侧来源目录选择数据快照、计算记录或正文引用，开启核对任务；正文中的引用入口会保留各自的导航现场。'
      const summary = document.createElement('div')
      summary.className = 'evidence-start-summary'
      start.append(summary)
      workspace.append(start)
      renderStartSummary()
      renderingWorkspace = false
      return
    }
    pageController = new AbortController()
    const signal = pageController.signal
    const task = state.currentTask()!
    if (!taskGraphs.has(task)) taskGraphs.set(task, createEvidenceGraph())
    const context = {
      graph: taskGraphs.get(task)!,
      taskLabel: task.root.label,
      client: options.client,
      page,
      signal,
      isStale: () => signal.aborted,
      revisionLabel: options.revisionLabel,
      labelFor: (ref: EvidenceObjectRef) => {
        const id = evidenceRefId(ref)
        return directoryRefs.find((item) => evidenceRefId(item) === id)?.label
      },
      downloadEnabled,
      drilldownEnabled,
      loadSources,
      navigate: (ref: EvidenceObjectRef) => {
        const before = state.currentPage()
        const next = state.navigate(ref)
        if (next && next !== before) {
          renderAll()
          announce(`已进入 ${ref.label}`)
        }
      },
      openBackground: (ref: EvidenceObjectRef, foreground = false) => {
        const task = state.openTask(ref, { foreground })
        if (foreground) renderAll()
        else renderTabs()
        persist()
        announce(`${foreground ? '已打开' : '已在后台开启'}核对任务 ${task.root.label}`)
      },
      setPreview: (ref: EvidenceObjectRef | null) => {
        const focus = ref ?? state.currentPage()?.selected ?? undefined
        const graph = workspace.querySelector<HTMLElement>('.evidence-graph-scroll')
        const scroll = graph?.scrollLeft ?? state.currentPage()?.graphScroll.left ?? 0
        const graphTop = graph?.scrollTop ?? state.currentPage()?.graphScroll.top ?? 0
        state.updatePage({ selected: ref, graphScroll: { left: scroll, top: graphTop } })
        persist()
        renderWorkspace(focus, scroll)
      },
      updatePage: (patch: Partial<Omit<EvidencePage, 'ref' | 'path'>>) =>
        {
          if (signal.aborted) return
          state.updatePage(patch)
          persist()
        },
      locateSubject: (subjectId: string) => {
        hideShell()
        options.locateSubject(subjectId)
      },
      getDraft: () => options.getDraft?.() ?? null,
      pageData: <T,>() => pageDataCache.get(page) as T | undefined,
      setPageData: (data: unknown) => pageDataCache.set(page, data),
    }
    void renderEvidencePage(workspace, context).then(() => {
      if (signal.aborted) return
      const graph = workspace.querySelector<HTMLElement>('.evidence-graph-scroll')
      if (graph) {
        graph.scrollLeft = graphScroll ?? page.graphScroll.left
        graph.scrollTop = page.graphScroll.top
      }
      renderingWorkspace = false
      if (focusNode) {
        const node = [...workspace.querySelectorAll<HTMLButtonElement>('.evidence-node')]
          .find((item) => item.dataset.evidenceNode === evidenceRefId(focusNode))
        node?.focus({ preventScroll: true })
      }
    })
  }

  // 打开失败等需要用户看到的提示；下次渲染（切换页签、导航等）即清除。
  const notice = shell.querySelector<HTMLElement>('.evidence-notice')!
  const showNotice = (message: string) => {
    notice.textContent = message
    notice.hidden = false
  }

  const renderAll = () => {
    notice.hidden = true
    navigationIntent += 1
    renderTabs()
    renderNav()
    renderDirectoryItems()
    renderWorkspace()
    persist()
  }

  const showShell = () => {
    if (!isOpen) options.onOpen?.()
    isOpen = true
    shell.hidden = false
    if (state.store.active === REPORT_TAB && state.store.tasks.length) {
      const latest = state.store.tasks.reduce((a, b) => (a.used > b.used ? a : b))
      state.switchTask(latest.key)
    }
    renderAll()
    void loadDirectory()
  }

  function hideShell() {
    navigationIntent += 1
    directoryController?.abort()
    isOpen = false
    pageController?.abort()
    shell.hidden = true
    setDirectoryOpen(false)
    closePickers()
    renderTabs()
    persist()
    options.onReturnToReport()
  }

  const openSubject = async (subjectId: string): Promise<void> => {
    showShell()
    const intent = ++navigationIntent
    try {
      const sources = await loadSources()
      if (!isOpen || intent !== navigationIntent) return
      const subject = sources.subjects?.find((item) => item.subjectId === subjectId)
      if (!subject) throw new ReportEditorApiError(404, 'source_missing')
      const ref: EvidenceObjectRef = {
        kind: 'subject',
        key: subject.subjectId,
        label: subjectLabel(subject.subjectId),
      }
      const task = state.openTask(ref, { foreground: true })
      renderAll()
      announce(`已开启核对任务 ${task.root.label}`)
    } catch (error) {
      if (!isOpen || intent !== navigationIntent) return
      const message = error instanceof ReportEditorApiError && error.code === 'source_missing'
        ? '该正文引用不在当前修订的来源中，可能已被修改或删除'
        : '来源定位失败，请稍后重试'
      announce(message)
      showNotice(message)
    }
  }

  return {
    open: showShell,
    close: hideShell,
    openSubject,
    /** 开启或激活指定对象的核对任务（供外部深链）。 */
    openObject(ref: EvidenceObjectRef) {
      showShell()
      state.openTask(ref, { foreground: true })
      renderAll()
    },
    setDownloadEnabled(enabled: boolean) {
      downloadEnabled = enabled
    },
    setDrilldownEnabled(enabled: boolean) {
      drilldownEnabled = enabled
    },
    /** 修订上下文变化（恢复历史版本）后丢弃全部任务现场。 */
    reset() {
      pageController?.abort()
      sourcesController?.abort()
      state.store.tasks.splice(0)
      state.closedTasks.splice(0)
      state.store.active = REPORT_TAB
      pageController = null
      sourcesPromise = null
      directoryRefs = []
      try { sessionStorage.removeItem(storageKey) } catch { /* ignore storage failures */ }
      hideShell()
    },
    isOpen: () => isOpen,
    _state: state,
  }
}

export type EvidenceBrowser = ReturnType<typeof createEvidenceBrowser>
