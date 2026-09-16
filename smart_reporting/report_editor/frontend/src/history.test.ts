import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createHistoryController } from './history'

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
})
