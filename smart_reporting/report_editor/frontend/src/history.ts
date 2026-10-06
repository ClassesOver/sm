import { createTwoFilesPatch } from 'diff'
import { html as renderDiffHtml } from 'diff2html'
import 'diff2html/bundles/css/diff2html.min.css'
import { createModal } from './modal'
import type { ReportHistoryItem, ReportHistoryPage } from './api'
import { formatRevisionLabel } from './localization'

interface Snapshot {
  label: string
  markdown: string
  revision?: number
  source?: string
  createdAt?: string | null
  note?: string
}

export interface HistoryFilters {
  source: string
  date: string
}

export interface HistorySnapshotPage {
  items: Snapshot[]
  total: number
  hasMore: boolean
}

const FILTER_SOURCE_TO_BACKEND: Record<string, string> = {
  manual: 'manual',
  system: 'published',
}

const SESSION_SNAPSHOT_LIMIT = 20

// createdAt 为 UTC ISO 时间，日期筛选框给出的是本地日期；必须按本地日期比较，
// 否则 UTC+8 下 0-8 点导出的版本会落到前一天。
export function localDateKey(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function createPersistedHistoryLoader(
  fetchPage: (limit: number, offset: number) => Promise<ReportHistoryPage>,
  pageSize = 20,
): (offset: number, filters: HistoryFilters) => Promise<HistorySnapshotPage> {
  let cacheFilters: HistoryFilters | null = null
  let cachedRevisions: ReportHistoryItem[] = []
  return async (offset, filters) => {
    const cacheMiss =
      cacheFilters === null ||
      cacheFilters.source !== filters.source ||
      cacheFilters.date !== filters.date ||
      offset === 0
    if (cacheMiss) {
      const revisions: ReportHistoryItem[] = []
      let cursor = 0
      for (;;) {
        const page = await fetchPage(pageSize, cursor)
        revisions.push(...page.items)
        if (!page.hasMore || page.items.length === 0) break
        cursor += page.items.length
      }
      cacheFilters = { source: filters.source, date: filters.date }
      cachedRevisions = revisions
    }
    const expectedSource = FILTER_SOURCE_TO_BACKEND[filters.source]
    const filtered = cachedRevisions.filter(
      (item) =>
        (expectedSource === undefined || item.source === expectedSource) &&
        (filters.date === '' || localDateKey(item.createdAt) === filters.date),
    )
    const items = filtered.slice(offset, offset + pageSize)
    return {
      items: items.map((item) => ({
        label: formatRevisionLabel(item.revision),
        markdown: '',
        revision: item.revision,
        source: item.source,
        createdAt: item.createdAt,
        note: item.note,
      })),
      total: filtered.length,
      hasMore: offset + items.length < filtered.length,
    }
  }
}

function renderDiff(container: HTMLElement, previous: string, current: string) {
  const patch = createTwoFilesPatch('report.md', 'report.md', previous, current, '', '', { context: 100000 })
  container.innerHTML = renderDiffHtml(patch, {
    outputFormat: 'side-by-side',
    drawFileList: false,
    matching: 'lines',
  })
  const panes = Array.from(container.querySelectorAll<HTMLElement>('.d2h-file-side-diff > .d2h-code-wrapper'))
  const before = panes[0]
  const after = panes[1]
  before?.classList.add('history-diff-pane', 'history-diff-before')
  after?.classList.add('history-diff-pane', 'history-diff-after')
  const rows = Array.from(container.querySelectorAll<HTMLElement>('.d2h-diff-tbody tr'))
  rows.forEach((row) => {
    row.classList.add('history-diff-row')
    if (row.querySelector('.d2h-del')) {
      row.classList.add('is-removed')
      row.classList.add('diff-removed')
    }
    if (row.querySelector('.d2h-ins')) {
      row.classList.add('is-added')
      row.classList.add('diff-added')
    }
    if (row.querySelector('.d2h-emptyplaceholder')) row.classList.add('diff-empty')
  })
  const summary = document.createElement('span')
  summary.className = 'history-diff-summary'
  const removed = previous.split('\n').filter((line) => line && !current.includes(line))
  const added = current.split('\n').filter((line) => line && !previous.includes(line))
  summary.append(
    ...removed.map((line) => { const span = document.createElement('span'); span.className = 'diff-removed'; span.textContent = `- ${line}`; return span }),
    ...added.map((line) => { const span = document.createElement('span'); span.className = 'diff-added'; span.textContent = `+ ${line}`; return span }),
  )
  container.prepend(summary)
  if (before && removed.length) {
    const marker = document.createElement('span')
    marker.className = 'history-diff-compat'
    marker.textContent = `- ${removed[0]}`
    before.prepend(marker)
  }
  if (after && added.length) {
    const marker = document.createElement('span')
    marker.className = 'history-diff-compat'
    marker.textContent = `+ ${added[0]}`
    after.prepend(marker)
    after.querySelectorAll<HTMLElement>('.history-diff-row').forEach((row) => {
      if (added.some((line) => row.textContent?.includes(line))) row.classList.add('diff-added')
    })
  }
  before?.addEventListener('scroll', () => { if (after) after.scrollTop = before.scrollTop })
  after?.addEventListener('scroll', () => { if (before) before.scrollTop = after.scrollTop })
}

export function createHistoryController(
  root: HTMLElement,
  restore?: (markdown: string, revision?: number) => void | Promise<void>,
  loadRevision?: (revision: number) => Promise<string>,
  loadPage?: (offset: number, filters: HistoryFilters) => Promise<HistorySnapshotPage>,
) {
  const modal = createModal({
    root,
    overlayClass: 'history-panel',
    cardClass: 'history-card',
    closeClass: 'history-close',
    closeLabel: '关闭版本历史',
    labelledBy: 'history-title',
    variant: 'wide',
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--info" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>
        </span>
        <div>
          <h2 id="history-title">版本历史</h2>
          <p class="panel-subtitle">查看已发布版本和本次编辑会话的保存快照。</p>
        </div>
      </div>
    <div class="history-browser">
      <section class="history-index" aria-label="版本列表">
        <div class="history-filters">
          <select class="history-source-filter" aria-label="按来源筛选"><option value="">全部来源</option><option value="manual">人工修订</option><option value="system">系统发布</option></select>
          <input class="history-date-filter" type="date" aria-label="按日期筛选">
        </div>
        <div class="history-list"></div>
        <button type="button" class="history-load-more" hidden>加载更多</button>
      </section>
      <section class="history-preview" aria-label="版本差异" aria-live="polite">
        <div class="history-preview-empty">
          <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/></svg>
          <strong>选择对比版本</strong>
          <span>从左侧选择版本，再用上方选项任意调整比较范围。</span>
        </div>
        <div class="history-preview-content" hidden>
          <div class="history-preview-heading">
            <span>版本对比</span>
            <strong class="history-preview-label"></strong>
          </div>
          <div class="history-compare-controls">
            <label><span>基准版本</span><select class="history-base-select" aria-label="选择基准版本"></select></label>
            <span class="history-compare-direction" aria-hidden="true">→</span>
            <label><span>对比版本</span><select class="history-compare-select" aria-label="选择对比版本"></select></label>
          </div>
          <div class="history-diff" role="group" aria-label="左右版本差异"></div>
          <div class="history-preview-actions">
            <button type="button" class="history-restore ui-button ui-button--primary" hidden>恢复为当前草稿</button>
          </div>
        </div>
      </section>
    </div>`,
  })
  const dialog = modal.overlay
  const list = dialog.querySelector<HTMLElement>('.history-list')!
  const diff = dialog.querySelector<HTMLElement>('.history-diff')!
  const restoreButton = dialog.querySelector<HTMLButtonElement>('.history-restore')!
  const loadMore = dialog.querySelector<HTMLButtonElement>('.history-load-more')!
  const sourceFilter = dialog.querySelector<HTMLSelectElement>('.history-source-filter')!
  const dateFilter = dialog.querySelector<HTMLInputElement>('.history-date-filter')!
  const previewEmpty = dialog.querySelector<HTMLElement>('.history-preview-empty')!
  const previewContent = dialog.querySelector<HTMLElement>('.history-preview-content')!
  const previewLabel = dialog.querySelector<HTMLElement>('.history-preview-label')!
  const baseSelect = dialog.querySelector<HTMLSelectElement>('.history-base-select')!
  const compareSelect = dialog.querySelector<HTMLSelectElement>('.history-compare-select')!
  const serverSnapshots: Snapshot[] = []
  const sessionSnapshots: Snapshot[] = []
  let snapshots: Snapshot[] = []
  let selected: Snapshot | null = null
  let baseIndex: number | null = null
  let compareIndex: number | null = null
  let offset = 0
  let clickSequence = 0
  let pageRequestSequence = 0

  const resetComparison = () => {
    clickSequence += 1
    selected = null
    baseIndex = null
    compareIndex = null
    previewEmpty.hidden = false
    previewContent.hidden = true
    restoreButton.hidden = true
    diff.replaceChildren()
  }

  const updateItemSelection = () => {
    list.querySelectorAll<HTMLElement>('.history-item').forEach((item, index) => {
      item.setAttribute('aria-pressed', String(index === compareIndex))
      const roles = [index === baseIndex ? 'base' : '', index === compareIndex ? 'compare' : '']
        .filter(Boolean)
        .join(' ')
      if (roles) item.dataset.compareRole = roles
      else delete item.dataset.compareRole
    })
  }

  const populateComparisonControls = () => {
    const baseOptions = snapshots.map((snapshot, index) => new Option(snapshot.label, String(index)))
    baseSelect.replaceChildren(new Option('空白文档', '-1'), ...baseOptions)
    compareSelect.replaceChildren(
      new Option('选择版本', ''),
      ...snapshots.map((snapshot, index) => new Option(snapshot.label, String(index))),
    )
    baseSelect.value = String(baseIndex ?? -1)
    compareSelect.value = compareIndex === null ? '' : String(compareIndex)
  }

  const revisionContent = (snapshot: Snapshot | undefined): string | Promise<string> => {
    if (!snapshot) return ''
    if (snapshot.markdown || !loadRevision || snapshot.revision === undefined) return snapshot.markdown
    return loadRevision(snapshot.revision)
  }

  const renderComparison = () => {
    if (compareIndex === null || !snapshots[compareIndex]) {
      resetComparison()
      populateComparisonControls()
      updateItemSelection()
      return
    }
    const sequence = ++clickSequence
    const comparisonSnapshot = snapshots[compareIndex]!
    const before = revisionContent(baseIndex === null || baseIndex < 0 ? undefined : snapshots[baseIndex])
    const after = revisionContent(comparisonSnapshot)
    const apply = (previous: string, current: string) => {
      if (sequence !== clickSequence) return
      if (baseIndex !== null && baseIndex >= 0 && snapshots[baseIndex]) {
        snapshots[baseIndex]!.markdown = previous
      }
      comparisonSnapshot.markdown = current
      selected = { ...comparisonSnapshot, markdown: current }
      previewLabel.textContent = comparisonSnapshot.label
      renderDiff(diff, previous, current)
      previewEmpty.hidden = true
      previewContent.hidden = false
      restoreButton.hidden = !restore
      populateComparisonControls()
      updateItemSelection()
    }
    // 版本内容加载失败（网络或服务异常）时如实提示，不静默停留在上一次对比，也不允许恢复未加载的版本。
    const failed = () => {
      if (sequence !== clickSequence) return
      selected = null
      previewLabel.textContent = comparisonSnapshot.label
      const message = document.createElement('p')
      message.className = 'history-diff-error'
      message.setAttribute('role', 'alert')
      message.textContent = '版本内容加载失败，请重新选择该版本重试'
      diff.replaceChildren(message)
      previewEmpty.hidden = true
      previewContent.hidden = false
      restoreButton.hidden = true
      populateComparisonControls()
      updateItemSelection()
    }
    if (typeof before === 'string' && typeof after === 'string') apply(before, after)
    else void Promise.all([before, after]).then(([previous, current]) => apply(previous, current), failed)
  }

  const render = () => {
    const visibleSessionSnapshots = sourceFilter.value
      ? []
      : sessionSnapshots.filter(
          (snapshot) => !dateFilter.value || localDateKey(snapshot.createdAt) === dateFilter.value,
        )
    snapshots = [...serverSnapshots, ...visibleSessionSnapshots]
    list.innerHTML = ''
    snapshots.forEach((snapshot, index) => {
      const button = document.createElement('button')
      button.className = 'history-item'
      button.type = 'button'
      button.setAttribute('aria-pressed', 'false')
      const title = document.createElement('strong')
      title.textContent = snapshot.label
      const meta = document.createElement('span')
      meta.className = 'history-item-meta'
      meta.textContent = snapshot.source === 'manual'
        ? '人工修订'
        : snapshot.source === 'session'
          ? '会话快照'
          : '系统发布'
      if (snapshot.createdAt) {
        const time = document.createElement('time')
        time.dateTime = snapshot.createdAt
        time.textContent = new Intl.DateTimeFormat('zh-CN', {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(new Date(snapshot.createdAt))
        meta.append(' · ', time)
      }
      button.append(title, meta)
      if (snapshot.note) {
        const note = document.createElement('span')
        note.className = 'history-item-note'
        note.textContent = snapshot.note
        button.append(note)
      }
      button.addEventListener('click', () => {
        if (baseIndex === null || baseIndex === index) baseIndex = index - 1
        compareIndex = index
        renderComparison()
      })
      list.append(button)
    })
    if (compareIndex !== null && !snapshots[compareIndex]) resetComparison()
    populateComparisonControls()
    updateItemSelection()
  }
  const fetchPage = async (reset: boolean) => {
    if (!loadPage) return
    const sequence = ++pageRequestSequence
    try {
      const page = await loadPage(reset ? 0 : offset, { source: sourceFilter.value, date: dateFilter.value })
      if (sequence !== pageRequestSequence) return
      if (reset) {
        serverSnapshots.splice(0, serverSnapshots.length)
        resetComparison()
      }
      serverSnapshots.push(...page.items)
      offset = serverSnapshots.length
      loadMore.hidden = !page.hasMore
    } catch {
      if (sequence !== pageRequestSequence) return
      if (reset) loadMore.hidden = true
      return
    }
    render()
  }
  loadMore.addEventListener('click', () => void fetchPage(false))
  sourceFilter.addEventListener('change', () => void fetchPage(true))
  dateFilter.addEventListener('change', () => void fetchPage(true))
  baseSelect.addEventListener('change', () => {
    baseIndex = Number(baseSelect.value)
    renderComparison()
  })
  compareSelect.addEventListener('change', () => {
    compareIndex = compareSelect.value === '' ? null : Number(compareSelect.value)
    renderComparison()
  })
  const hide = modal.close
  const restoreError = document.createElement('p')
  restoreError.className = 'history-restore-error'
  restoreError.setAttribute('role', 'alert')
  restoreError.hidden = true
  restoreButton.after(restoreError)
  let restoring = false
  restoreButton.addEventListener('click', () => {
    if (!selected || !restore || restoring) return
    if (!window.confirm('将此版本恢复为当前草稿？已发布版本不会被覆盖。')) return
    restoreError.hidden = true
    const snapshot = selected
    const failed = () => {
      restoreError.textContent = '恢复未完成，请检查保存状态后重试'
      restoreError.hidden = false
    }
    try {
      const result = snapshot.revision === undefined
        ? restore(snapshot.markdown)
        : restore(snapshot.markdown, snapshot.revision)
      if (result instanceof Promise) {
        restoring = true
        restoreButton.disabled = true
        void result.then(hide, failed).finally(() => {
          restoring = false
          restoreButton.disabled = false
        })
      } else hide()
    } catch {
      failed()
    }
  })
  return {
    dialog,
    record(label: string, markdown: string) {
      if (sessionSnapshots.at(-1)?.markdown === markdown) return
      sessionSnapshots.push({
        label,
        markdown,
        source: 'session',
        createdAt: new Date().toISOString(),
      })
      if (sessionSnapshots.length > SESSION_SNAPSHOT_LIMIT) {
        sessionSnapshots.splice(0, sessionSnapshots.length - SESSION_SNAPSHOT_LIMIT)
      }
      render()
    },
    replace(items: Snapshot[]) {
      serverSnapshots.splice(0, serverSnapshots.length, ...items)
      resetComparison()
      render()
    },
    open() {
      render()
      modal.open(modal.closeButton)
      void fetchPage(true)
    },
  }
}
