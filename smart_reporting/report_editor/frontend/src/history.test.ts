import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createHistoryController, createPersistedHistoryLoader } from './history'

describe('createHistoryController', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>'
  })

  it('lists snapshots and renders a line diff', () => {
    const controller = createHistoryController(document.body)
    controller.record('Revision 1', '# 摘要\n旧内容')
    controller.record('Revision 2', '# 摘要\n新内容')
    controller.open()

    expect(document.querySelectorAll('.history-item')).toHaveLength(2)
    document.querySelector<HTMLButtonElement>('.history-item:last-child')!.click()
    expect(document.querySelector('.history-diff')?.textContent).toContain('+ 新内容')
    expect(document.querySelector('.history-diff')?.textContent).toContain('- 旧内容')
    expect(document.querySelector('.diff-added')?.textContent).toBe('+ 新内容')
    expect(document.querySelector('.diff-removed')?.textContent).toBe('- 旧内容')
  })

  it('keeps an isolated insertion local to one diff hunk', () => {
    const controller = createHistoryController(document.body)
    controller.record('Revision 1', '# 标题\n第一段\n第二段')
    controller.record('Revision 2', '# 标题\n新增段\n第一段\n第二段')
    controller.open()
    document.querySelector<HTMLButtonElement>('.history-item:last-child')!.click()
    const diff = document.querySelector('.history-diff')?.textContent ?? ''
    expect(diff).toContain('+ 新增段')
    expect(diff).toContain('  第一段')
    expect(diff).toContain('  第二段')
    expect(diff).not.toContain('- 第一段')
    expect(diff).not.toContain('- 第二段')
  })

  it('restores a selected snapshot only after confirmation', () => {
    const restore = vi.fn()
    vi.stubGlobal('confirm', () => true)
    const controller = createHistoryController(document.body, restore)
    controller.record('Revision 1', '# 旧版本')
    controller.open()
    document.querySelector<HTMLButtonElement>('.history-item')!.click()
    document.querySelector<HTMLButtonElement>('.history-restore')!.click()
    expect(restore).toHaveBeenCalledWith('# 旧版本')
    expect(controller.dialog.hidden).toBe(true)
    vi.unstubAllGlobals()
  })

  it('loads selected and previous revisions for a useful diff', async () => {
    const loadRevision = vi.fn(async (revision: number) => (revision === 1 ? '# 旧\n' : '# 新\n'))
    const controller = createHistoryController(document.body, undefined, loadRevision)
    controller.replace([
      { label: 'Revision 1', markdown: '', revision: 1 },
      { label: 'Revision 2', markdown: '', revision: 2 },
    ])
    controller.open()
    document.querySelector<HTMLButtonElement>('.history-item:last-child')!.click()
    await Promise.resolve()
    await Promise.resolve()
    expect(document.querySelector('.history-diff')?.textContent).toContain('+ # 新')
    expect(document.querySelector('.history-diff')?.textContent).toContain('- # 旧')
    expect(loadRevision).toHaveBeenCalledWith(1)
    expect(loadRevision).toHaveBeenCalledWith(2)
  })

  it('shows revision source, creation time, and note', () => {
    const controller = createHistoryController(document.body)
    controller.replace([{
      label: 'Revision 2',
      markdown: '# 修订\n',
      revision: 2,
      source: 'manual',
      createdAt: '2026-09-16T08:30:00+08:00',
      note: '运营数据复核后发布',
    }])
    controller.open()

    const item = document.querySelector('.history-item')
    expect(item?.textContent).toContain('人工修订')
    expect(item?.textContent).toContain('运营数据复核后发布')
    expect(item?.querySelector('time')?.getAttribute('datetime')).toBe('2026-09-16T08:30:00+08:00')
  })

  it('loads more history and reloads when filters change', async () => {
    const loadPage = vi.fn()
      .mockResolvedValueOnce({ items: [{ label: 'Revision 3', markdown: '', revision: 3, source: 'manual' }], total: 2, hasMore: true })
      .mockResolvedValueOnce({ items: [{ label: 'Revision 2', markdown: '', revision: 2, source: 'system' }], total: 2, hasMore: false })
      .mockResolvedValueOnce({ items: [], total: 0, hasMore: false })
    const controller = createHistoryController(document.body, undefined, undefined, loadPage)
    controller.open()
    await vi.waitFor(() => expect(document.querySelectorAll('.history-item')).toHaveLength(1))
    document.querySelector<HTMLButtonElement>('.history-load-more')!.click()
    await vi.waitFor(() => expect(document.querySelectorAll('.history-item')).toHaveLength(2))
    const source = document.querySelector<HTMLSelectElement>('.history-source-filter')!
    source.value = 'manual'
    source.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(loadPage).toHaveBeenLastCalledWith(0, { source: 'manual', date: '' }))
  })

  it('reaches later server pages when a filter drops an entire first page', async () => {
    const revisions = Array.from({ length: 40 }, (_, index) => ({
      revision: index + 1,
      sha256: 'a'.repeat(64),
      source: index === 34 ? 'manual' : 'published',
      createdAt: '2026-09-16T08:30:00+00:00',
    }))
    const fetchPage = vi.fn(async (limit: number, offset: number) => {
      const items = revisions.slice(offset, offset + limit)
      return { items, total: revisions.length, hasMore: offset + items.length < revisions.length }
    })
    const loadPage = createPersistedHistoryLoader(fetchPage)
    const controller = createHistoryController(document.body, undefined, undefined, loadPage)
    controller.open()
    await vi.waitFor(() => expect(document.querySelectorAll('.history-item')).toHaveLength(20))
    const source = document.querySelector<HTMLSelectElement>('.history-source-filter')!
    source.value = 'manual'
    source.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(document.querySelector('.history-item strong')?.textContent).toBe('Revision 35'))
  })

  it('loads every matching revision exactly once across server pages', async () => {
    const revisions = Array.from({ length: 40 }, (_, index) => ({
      revision: index + 1,
      sha256: 'a'.repeat(64),
      source: index === 4 || index === 24 ? 'manual' : 'published',
    }))
    const fetchPage = vi.fn(async (limit: number, offset: number) => {
      const items = revisions.slice(offset, offset + limit)
      return { items, total: revisions.length, hasMore: offset + items.length < revisions.length }
    })
    const loadPage = createPersistedHistoryLoader(fetchPage, 1)

    const first = await loadPage(0, { source: 'manual', date: '' })
    expect(first.items.map((item) => item.label)).toEqual(['Revision 5'])
    expect(first.total).toBe(2)
    expect(first.hasMore).toBe(true)
    const second = await loadPage(1, { source: 'manual', date: '' })
    expect(second.items.map((item) => item.label)).toEqual(['Revision 25'])
    expect(second.hasMore).toBe(false)
  })

  it('maps the system filter onto published revisions', async () => {
    const fetchPage = vi.fn(async () => ({
      items: [{ revision: 1, sha256: 'a'.repeat(64), source: 'published', createdAt: '2026-09-16T08:30:00+00:00' }],
      total: 1,
      hasMore: false,
    }))
    const loadPage = createPersistedHistoryLoader(fetchPage)

    const result = await loadPage(0, { source: 'system', date: '' })

    expect(result.items).toHaveLength(1)
    expect(result.total).toBe(1)
    const manualOnly = await loadPage(0, { source: 'manual', date: '' })
    expect(manualOnly.items).toHaveLength(0)
    const dated = await loadPage(0, { source: 'system', date: '2026-09-16' })
    expect(dated.items).toHaveLength(1)
    const otherDay = await loadPage(0, { source: 'system', date: '2026-09-15' })
    expect(otherDay.items).toHaveLength(0)
  })

  it('keeps session snapshots when reloading persisted history', async () => {
    const loadPage = vi.fn().mockResolvedValue({
      items: [{ label: 'Revision 1', markdown: '', revision: 1 }],
      total: 1,
      hasMore: false,
    })
    const controller = createHistoryController(document.body, undefined, undefined, loadPage)
    controller.record('当前会话 · 已保存', '# 会话草稿')
    controller.open()

    await vi.waitFor(() =>
      expect(document.querySelectorAll('.history-item')).toHaveLength(2),
      { timeout: 200 },
    )
  })

  it('ignores out-of-order history clicks after a newer selection', async () => {
    let resolveFirst: ((markdown: string) => void) | undefined
    const loadRevision = vi.fn((revision: number) => {
      if (revision === 1) return new Promise<string>((resolve) => { resolveFirst = resolve })
      return Promise.resolve(`# 第${revision}版\n`)
    })
    const controller = createHistoryController(document.body, undefined, loadRevision)
    controller.replace([
      { label: 'Revision 1', markdown: '', revision: 1 },
      { label: 'Revision 2', markdown: '', revision: 2 },
      { label: 'Revision 3', markdown: '', revision: 3 },
    ])
    controller.open()
    const items = document.querySelectorAll<HTMLButtonElement>('.history-item')
    items[0]!.click()
    items[2]!.click()
    await vi.waitFor(() => expect(document.querySelector('.history-diff')?.textContent).toContain('+ # 第3版'))
    resolveFirst?.('# 第1版\n')
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(document.querySelector('.history-diff')?.textContent).toContain('+ # 第3版')
  })

  it('reuses the fetched revision list for load-more within the same filter', async () => {
    const fetchPage = vi.fn(async (limit: number, offset: number) => {
      const items = Array.from({ length: 5 }, (_, index) => ({
        revision: offset + index + 1,
        sha256: 'a'.repeat(64),
        source: 'published',
      }))
      return { items, total: 10, hasMore: offset + items.length < 10 }
    })
    const loader = createPersistedHistoryLoader(fetchPage, 5)

    await loader(0, { source: '', date: '' })
    expect(fetchPage).toHaveBeenCalledTimes(2)
    await loader(5, { source: '', date: '' })

    expect(fetchPage).toHaveBeenCalledTimes(2)
  })

  it('refetches when the loader is called from the first page again', async () => {
    const fetchPage = vi.fn(async (limit: number, offset: number) => {
      const items = Array.from({ length: 5 }, (_, index) => ({
        revision: offset + index + 1,
        sha256: 'a'.repeat(64),
        source: 'published',
      }))
      return { items, total: 10, hasMore: offset + items.length < 10 }
    })
    const loader = createPersistedHistoryLoader(fetchPage, 5)

    await loader(0, { source: '', date: '' })
    await loader(0, { source: '', date: '' })

    expect(fetchPage).toHaveBeenCalledTimes(4)
  })

  it('deduplicates consecutive identical session snapshots', () => {
    const controller = createHistoryController(document.body)
    controller.record('已保存 · 10:00', '# 相同内容\n')
    controller.record('已保存 · 10:01', '# 相同内容\n')
    controller.open()

    expect(document.querySelectorAll('.history-item')).toHaveLength(1)
  })

  it('caps session snapshots to a recent window', () => {
    const controller = createHistoryController(document.body)
    for (let index = 0; index < 25; index += 1) {
      controller.record(`保存 ${index}`, `# v${index}\n`)
    }
    controller.open()

    expect(document.querySelectorAll('.history-item')).toHaveLength(20)
    expect(document.querySelector('.history-item:last-child strong')?.textContent).toBe('保存 24')
  })

  it('closes the history panel with Escape', async () => {
    const loadPage = vi.fn().mockResolvedValue({ items: [], total: 0, hasMore: false })
    const controller = createHistoryController(document.body, undefined, undefined, loadPage)
    controller.open()
    await vi.waitFor(() => expect(controller.dialog.hidden).toBe(false))

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(controller.dialog.hidden).toBe(true)
  })

  it('keeps the latest filter results when an earlier request resolves late', async () => {
    let resolveInitial: ((page: {
      items: Array<{ label: string; markdown: string; revision: number; source: string }>
      total: number
      hasMore: boolean
    }) => void) | undefined
    let resolveManual: typeof resolveInitial
    const loadPage = vi.fn((_offset: number, filters: { source: string; date: string }) =>
      new Promise<{
        items: Array<{ label: string; markdown: string; revision: number; source: string }>
        total: number
        hasMore: boolean
      }>((resolve) => {
        if (filters.source === 'manual') resolveManual = resolve
        else resolveInitial = resolve
      }),
    )
    const controller = createHistoryController(document.body, undefined, undefined, loadPage)
    controller.open()
    await vi.waitFor(() => expect(loadPage).toHaveBeenCalledTimes(1))
    const source = document.querySelector<HTMLSelectElement>('.history-source-filter')!
    source.value = 'manual'
    source.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(loadPage).toHaveBeenCalledTimes(2))
    resolveManual?.({
      items: [{ label: 'Revision 2', markdown: '', revision: 2, source: 'manual' }],
      total: 1,
      hasMore: false,
    })
    await vi.waitFor(() => expect(document.querySelector('.history-item strong')?.textContent).toBe('Revision 2'))
    resolveInitial?.({
      items: [{ label: 'Revision 1', markdown: '', revision: 1, source: 'published' }],
      total: 1,
      hasMore: false,
    })
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(document.querySelector('.history-item strong')?.textContent).toBe('Revision 2')
  })

  it('labels local saves as session snapshots', () => {
    const controller = createHistoryController(document.body)
    controller.record('已保存 · 10:00', '# 会话内容\n')
    controller.open()

    expect(document.querySelector('.history-item-meta')?.textContent).toContain('会话快照')
  })

  it('hides session snapshots while a persisted source filter is active', async () => {
    const loadPage = vi.fn().mockResolvedValue({ items: [], total: 0, hasMore: false })
    const controller = createHistoryController(document.body, undefined, undefined, loadPage)
    controller.record('已保存 · 10:00', '# 会话内容\n')
    controller.open()
    await vi.waitFor(() => expect(document.querySelectorAll('.history-item')).toHaveLength(1))
    const source = document.querySelector<HTMLSelectElement>('.history-source-filter')!
    source.value = 'system'
    source.dispatchEvent(new Event('change'))

    await vi.waitFor(() => expect(document.querySelectorAll('.history-item')).toHaveLength(0))
  })
})
