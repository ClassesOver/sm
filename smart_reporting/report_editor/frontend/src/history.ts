import { diffLines as calculateLineDiff } from 'diff'
import { installFocusTrap } from './focus-trap'

interface Snapshot {
  label: string
  markdown: string
  revision?: number
  source?: string
  createdAt?: string | null
  note?: string
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
  loadPage?: (offset: number, filters: { source: string; date: string }) => Promise<{ items: Snapshot[]; total: number; hasMore: boolean }>,
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
  const snapshots: Snapshot[] = []
  let selected: Snapshot | null = null
  let opener: HTMLElement | null = null
  let offset = 0
  const render = () => {
    list.innerHTML = ''
    snapshots.forEach((snapshot, index) => {
      const button = document.createElement('button')
      button.className = 'history-item'
      button.type = 'button'
      const title = document.createElement('strong')
      title.textContent = snapshot.label
      const meta = document.createElement('span')
      meta.className = 'history-item-meta'
      meta.textContent = snapshot.source === 'manual' ? '人工修订' : '系统发布'
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
        void (async () => {
          const markdown = snapshot.markdown || (loadRevision && snapshot.revision !== undefined
            ? await loadRevision(snapshot.revision)
            : '')
          selected = { ...snapshot, markdown }
          const previousSnapshot = snapshots[index - 1]
          const previous = previousSnapshot?.markdown || (loadRevision && previousSnapshot?.revision !== undefined
            ? await loadRevision(previousSnapshot.revision)
            : '')
          if (previousSnapshot && !previousSnapshot.markdown) previousSnapshot.markdown = previous
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
    const page = await loadPage(reset ? 0 : offset, { source: sourceFilter.value, date: dateFilter.value })
    if (reset) snapshots.splice(0, snapshots.length)
    snapshots.push(...page.items)
    offset = snapshots.length
    loadMore.hidden = !page.hasMore
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
  return {
    dialog,
    record(label: string, markdown: string) {
      snapshots.push({ label, markdown })
      render()
    },
    replace(items: Snapshot[]) {
      snapshots.splice(0, snapshots.length, ...items)
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
