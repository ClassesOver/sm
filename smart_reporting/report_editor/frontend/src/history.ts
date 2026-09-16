import { diffLines as calculateLineDiff } from 'diff'
import { installFocusTrap } from './focus-trap'
import type { ReportHistoryItem, ReportHistoryPage } from './api'

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
        (filters.date === '' || (item.createdAt ?? '').startsWith(filters.date)),
    )
    const items = filtered.slice(offset, offset + pageSize)
    return {
      items: items.map((item) => ({
        label: `Revision ${item.revision}`,
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

function diffLines(previous: string, current: string): string {
  return calculateLineDiff(previous, current)
    .flatMap((part) => {
      const lines = part.value.split('\n')
      if (lines.at(-1) === '') lines.pop()
      const prefix = part.added ? '+ ' : part.removed ? '- ' : '  '
      return lines.map((line) => `${prefix}${line}`)
    })
    .join('\n')
}

function renderDiff(container: HTMLElement, value: string) {
  container.replaceChildren(
    ...value.split('\n').map((line) => {
      const row = document.createElement('span')
      row.className = line.startsWith('+ ')
        ? 'diff-added'
        : line.startsWith('- ')
          ? 'diff-removed'
          : 'diff-unchanged'
      row.textContent = line
      return row
    }),
  )
}

export function createHistoryController(
  root: HTMLElement,
  restore?: (markdown: string) => void,
  loadRevision?: (revision: number) => Promise<string>,
  loadPage?: (offset: number, filters: HistoryFilters) => Promise<HistorySnapshotPage>,
) {
  const dialog = document.createElement('div')
  dialog.className = 'history-panel'
  dialog.hidden = true
  dialog.innerHTML = `<section class="history-card" role="dialog" aria-modal="true" aria-labelledby="history-title"><button type="button" class="history-close" aria-label="关闭版本历史">×</button><h2 id="history-title">版本历史</h2><p class="history-note">包含已发布 revision 和本次编辑会话的保存快照。</p><div class="history-filters"><select class="history-source-filter" aria-label="按来源筛选"><option value="">全部来源</option><option value="manual">人工修订</option><option value="system">系统发布</option></select><input class="history-date-filter" type="date" aria-label="按日期筛选"></div><div class="history-list"></div><button type="button" class="history-load-more" hidden>加载更多</button><pre class="history-diff" hidden></pre><button type="button" class="history-restore" hidden>恢复为当前草稿</button></section>`
  root.append(dialog)
  installFocusTrap(dialog)
  const list = dialog.querySelector<HTMLElement>('.history-list')!
  const diff = dialog.querySelector<HTMLElement>('.history-diff')!
  const restoreButton = dialog.querySelector<HTMLButtonElement>('.history-restore')!
  const loadMore = dialog.querySelector<HTMLButtonElement>('.history-load-more')!
  const sourceFilter = dialog.querySelector<HTMLSelectElement>('.history-source-filter')!
  const dateFilter = dialog.querySelector<HTMLInputElement>('.history-date-filter')!
  const serverSnapshots: Snapshot[] = []
  const sessionSnapshots: Snapshot[] = []
  let snapshots: Snapshot[] = []
  let selected: Snapshot | null = null
  let opener: HTMLElement | null = null
  let offset = 0
  let clickSequence = 0
  let pageRequestSequence = 0
  const render = () => {
    const visibleSessionSnapshots = sourceFilter.value
      ? []
      : sessionSnapshots.filter(
          (snapshot) => !dateFilter.value || snapshot.createdAt?.startsWith(dateFilter.value),
        )
    snapshots = [...serverSnapshots, ...visibleSessionSnapshots]
    list.innerHTML = ''
    snapshots.forEach((snapshot, index) => {
      const button = document.createElement('button')
      button.className = 'history-item'
      button.type = 'button'
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
        const sequence = ++clickSequence
        void (async () => {
          const markdown = snapshot.markdown || (loadRevision && snapshot.revision !== undefined
            ? await loadRevision(snapshot.revision)
            : '')
          const previousSnapshot = snapshots[index - 1]
          const previous = previousSnapshot?.markdown || (loadRevision && previousSnapshot?.revision !== undefined
            ? await loadRevision(previousSnapshot.revision)
            : '')
          if (previousSnapshot && !previousSnapshot.markdown) previousSnapshot.markdown = previous
          if (sequence !== clickSequence) return
          selected = { ...snapshot, markdown }
          renderDiff(diff, diffLines(previous, markdown))
          diff.hidden = false
          restoreButton.hidden = !restore
        })()
      })
      list.append(button)
    })
  }
  const fetchPage = async (reset: boolean) => {
    if (!loadPage) return
    const sequence = ++pageRequestSequence
    try {
      const page = await loadPage(reset ? 0 : offset, { source: sourceFilter.value, date: dateFilter.value })
      if (sequence !== pageRequestSequence) return
      if (reset) serverSnapshots.splice(0, serverSnapshots.length)
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
  const hide = () => {
    dialog.hidden = true
    opener?.focus()
    opener = null
  }
  restoreButton.addEventListener('click', () => {
    if (!selected || !restore) return
    if (!window.confirm('将此版本恢复为当前草稿？已发布版本不会被覆盖。')) return
    restore(selected.markdown)
    hide()
  })
  dialog.querySelector<HTMLButtonElement>('.history-close')!.addEventListener('click', hide)
  dialog.addEventListener('click', (event) => { if (event.target === dialog) hide() })
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !dialog.hidden) hide()
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
      render()
    },
    open() {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      render()
      dialog.hidden = false
      void fetchPage(true)
      dialog.querySelector<HTMLButtonElement>('.history-close')?.focus()
    },
  }
}
