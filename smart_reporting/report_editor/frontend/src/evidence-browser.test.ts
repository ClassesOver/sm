import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReportEditorClient, type TraceSources } from './api'
import { createEvidenceBrowser } from './evidence-browser'
import type { EvidenceObjectRef } from './evidence-state'

const PAYLOADS: Record<string, unknown> = {
  '/api/sources': {
    available: true,
    datasets: [
      {
        datasetId: 'dataset-1',
        sourceType: 'url_csv',
        requirementId: 'att-1',
        filename: '收入明细.csv',
        businessLabel: null,
        rowCount: 4,
        size: 125,
        materializedAt: '2026-09-29T08:00:00Z',
        periodRoles: ['current'],
        queryWindowId: 'current',
      },
    ],
    subjects: [
      {
        subjectId: 'sub-aaaa',
        subjectKind: 'text_claim',
        locator: { sectionId: 'section_002' },
        factRefs: [{ analysisId: 'analysis_001', factId: 'fact-a' }],
        computationId: null,
      },
    ],
    drilldown: { enabled: false, metrics: [], subjects: [] },
  },
  '/api/computations': {
    available: true,
    computations: [
      {
        computationId: 'comp-1',
        method: '渠道收入汇总',
        methodVersion: null,
        executionId: null,
        verification: 'verified',
        reproducibility: 'limited',
        inputDatasetCount: 1,
        outputFactCount: 1,
        scriptSize: null,
        limitations: [],
      },
    ],
  },
  '/api/charts': { available: false },
  '/api/datasets/dataset-1/preview': {
    datasetId: 'dataset-1', columns: ['region'], rows: [['华东'], ['华北']],
    rowCountTotal: 2, offset: 0, limit: 50, nextCursor: null,
    truncatedCells: 0, truncatedByBudget: false, cellTruncationNote: null,
  },
}

function makeClient() {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const path = Object.keys(PAYLOADS).find((key) => url.includes(key))
    return new Response(JSON.stringify(path ? PAYLOADS[path] : {}), { status: 200 })
  }) as unknown as typeof fetch
  return new ReportEditorClient('/reports/v1/editor/report-1/12', fetcher)
}

function setup(client = makeClient()) {
  const root = document.createElement('div')
  document.body.append(root)
  const onReturnToReport = vi.fn()
  const onOpen = vi.fn()
  const browser = createEvidenceBrowser(root, {
    client,
    revisionLabel: '修订 12',
    onReturnToReport,
    onOpen,
    locateSubject: vi.fn(),
  })
  const shell = root.querySelector<HTMLElement>('.evidence-shell')!
  return { root, browser, shell, onReturnToReport, onOpen }
}

const fact = (key: string, label = key): EvidenceObjectRef => ({
  kind: 'fact',
  key,
  analysisId: 'analysis_001',
  label,
})

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

afterEach(() => {
  sessionStorage.clear()
})

describe('evidence browser shell', () => {
  it('restores the last closed task through the task picker and clears it on revision reset', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    browser._state.navigate({ kind: 'dataset', key: 'dataset-1', label: '收入明细.csv' })
    browser._state.updatePage({ filter: '华东' })
    shell.querySelector<HTMLButtonElement>('.evidence-tab-close')!.click()
    browser.open()
    await flush()
    const restore = () => [...shell.querySelectorAll<HTMLButtonElement>('.evidence-task-items button')]
      .find((button) => button.textContent === '恢复最近关闭的任务')!
    expect(restore().disabled).toBe(false)
    restore().click()
    await flush()
    expect(browser._state.currentTask()?.root.label).toBe('华东营收')
    expect(browser._state.currentPage()?.filter).toBe('华东')
    expect(shell.querySelector<HTMLInputElement>('.evidence-filter')?.value).toBe('华东')
    shell.querySelector<HTMLButtonElement>('.evidence-tab-close')!.click()
    browser.reset()
    browser.open()
    expect(restore().disabled).toBe(true)
    expect(browser._state.restoreTask()).toBeNull()
  })

  it('opens hidden shell with fixed report tab and start page', async () => {
    const { shell, browser } = setup()
    expect(shell.hidden).toBe(true)
    browser.open()
    await flush()
    expect(shell.hidden).toBe(false)
    const tabs = shell.querySelectorAll('.evidence-tab')
    expect(tabs).toHaveLength(1)
    expect(tabs[0].textContent).toBe('报告正文')
    expect(shell.querySelector('.evidence-start')).not.toBeNull()
    expect(shell.querySelector('.evidence-revision')!.textContent).toBe('修订 12')
  })

  it('renders icon affordances for navigation and task controls', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    await flush()
    expect(shell.querySelector<HTMLButtonElement>('[data-evidence="back"] svg')).not.toBeNull()
    expect(shell.querySelector<HTMLButtonElement>('[data-evidence="forward"] svg')).not.toBeNull()
    expect(shell.querySelector('.evidence-path-picker summary svg')).not.toBeNull()
    const close = shell.querySelector<HTMLButtonElement>('.evidence-tab-close')!
    expect(close.getAttribute('aria-label')).toContain('关闭核对任务')
    expect(close.querySelector('svg')).not.toBeNull()
  })

  it('loads the source directory and opens an independent task per item', async () => {
    const { shell, browser } = setup()
    browser.open()
    await flush()
    await flush()
    const items = shell.querySelectorAll<HTMLButtonElement>('.evidence-directory-item')
    const labels = [...items].map((item) => item.textContent)
    expect(labels).toContain('收入明细.csv')
    expect(labels).toContain('渠道收入汇总')

    items[0].click()
    await flush()
    const tabs = shell.querySelectorAll('.evidence-tab')
    expect(tabs).toHaveLength(2)
    expect(shell.querySelector('.evidence-tab-name')!.textContent).toBe('收入明细.csv')
    expect(shell.querySelector('.evidence-tab-stage')!.textContent).toBe('快照')
    // 面包屑从任务起点开始，当前对象标记 aria-current。
    const current = shell.querySelector('.evidence-crumb-current')!
    expect(current.textContent).toBe('收入明细.csv')
    expect(current.getAttribute('aria-current')).toBe('page')
  })

  it('associates the active task tab with the evidence tabpanel', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    await flush()
    const tab = shell.querySelector<HTMLButtonElement>('.evidence-tab:not(.evidence-tab-report)')!
    const workspace = shell.querySelector<HTMLElement>('.evidence-workspace')!
    expect(tab.getAttribute('role')).toBe('tab')
    expect(tab.getAttribute('aria-controls')).toBe(workspace.id)
    expect(workspace.getAttribute('role')).toBe('tabpanel')
    expect(workspace.getAttribute('aria-labelledby')).toBe(tab.id)
  })

  it('scrolls the tab strip so a newly active task tab is visible', async () => {
    const { shell, browser } = setup()
    const tabList = shell.querySelector<HTMLElement>('.evidence-tabs')!
    let scrollLeft = 0
    Object.defineProperty(tabList, 'scrollLeft', { get: () => scrollLeft, set: (value: number) => { scrollLeft = value } })
    Object.defineProperty(tabList, 'scrollWidth', { get: () => 900 })
    Object.defineProperty(tabList, 'clientWidth', { get: () => 300 })
    const rect = (left: number, right: number) => ({ left, right, top: 0, bottom: 40, width: right - left, height: 40, x: left, y: 0, toJSON: () => ({}) }) as DOMRect
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this === tabList) return rect(0, 300)
      const tab = this.querySelector('.evidence-tab')
      return tab?.getAttribute('aria-selected') === 'true' ? rect(400, 520) : rect(0, 0)
    })
    try {
      browser.openObject(fact('fact-c', '华南营收'))
      await flush()
      // 当前页签右缘 520 超出可见区 300，应只在页签栏内水平滚动到可见并留 8px。
      expect(scrollLeft).toBe(228)
    } finally {
      spy.mockRestore()
    }
  })

  it('uses roving tabindex for manually activated task tabs', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    browser._state.openTask(fact('fact-b', '华北营收'))
    browser.open()
    await flush()
    const tabs = [...shell.querySelectorAll<HTMLButtonElement>('.evidence-tab')]
    const active = tabs.find(tab => tab.getAttribute('aria-selected') === 'true')!
    expect(active.tabIndex).toBe(0)
    expect(tabs.filter(tab => tab !== active).every(tab => tab.tabIndex === -1)).toBe(true)
    active.focus()
    active.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(document.activeElement).toBe(tabs[(tabs.indexOf(active) + 1) % tabs.length])
  })

  it('directory search filters items without touching task state', async () => {
    const { shell, browser } = setup()
    browser.open()
    await flush()
    await flush()
    const search = shell.querySelector<HTMLInputElement>('.evidence-directory-search')!
    search.value = '渠道'
    search.dispatchEvent(new Event('input'))
    const labels = [...shell.querySelectorAll('.evidence-directory-item')].map((i) => i.textContent)
    expect(labels).toEqual(['渠道收入汇总'])
    // 目录条目带类型图标，图标仅作装饰，不改变可读名称。
    const icon = shell.querySelector('.evidence-directory-item .evidence-directory-icon')
    expect(icon?.getAttribute('aria-hidden')).toBe('true')
    expect(shell.querySelectorAll('.evidence-tab')).toHaveLength(1)
  })

  it('report tab hides the shell and keeps task state for reopening', async () => {
    const { shell, browser, onReturnToReport } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    await flush()
    expect(shell.querySelectorAll('.evidence-tab')).toHaveLength(2)
    ;[...shell.querySelectorAll<HTMLButtonElement>('.evidence-tab')]
      .find((tab) => tab.dataset.evidenceTab === 'report')!
      .click()
    expect(shell.hidden).toBe(true)
    expect(onReturnToReport).toHaveBeenCalledOnce()
    browser.open()
    await flush()
    expect(shell.hidden).toBe(false)
    expect(shell.querySelector('.evidence-tab-name')!.textContent).toBe('华东营收')
  })

  it('captures the editor scene only when entering the browser, not on task switches', async () => {
    const { browser, onOpen, onReturnToReport } = setup()
    browser.openObject(fact('a'))
    browser.openObject(fact('b'))
    await flush()
    expect(onOpen).toHaveBeenCalledTimes(1)
    browser.close()
    expect(onReturnToReport).toHaveBeenCalledTimes(1)
    browser.open()
    expect(onOpen).toHaveBeenCalledTimes(2)
  })

  it('restores task history after a browser instance is recreated', async () => {
    const first = setup()
    first.browser.openObject(fact('fact-a', '华东营收'))
    await flush()
    // 使用相同键验证刷新恢复；先把第一实例写入同一隔离存储。
    sessionStorage.setItem('evidence-browser-test-restore', JSON.stringify(first.browser._state.store))
    const restoredRoot = document.createElement('div')
    document.body.append(restoredRoot)
    const restored = createEvidenceBrowser(restoredRoot, {
      client: makeClient(),
      revisionLabel: '修订 12',
      onReturnToReport: vi.fn(),
      locateSubject: vi.fn(),
      storageKey: 'evidence-browser-test-restore',
    })
    restored.open()
    await flush()
    expect(restored._state.store.tasks).toHaveLength(1)
    expect(restored._state.currentPage()?.ref.key).toBe('fact-a')
  })

  it('tab keyboard moves focus without activating, Enter activates, Delete closes', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    browser.openObject(fact('fact-b', '华北营收'))
    await flush()
    const tabs = () => [...shell.querySelectorAll<HTMLButtonElement>('.evidence-tab')]
    tabs()[0].focus()
    const tabList = shell.querySelector('.evidence-tabs')!
    tabList.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(document.activeElement).toBe(tabs()[1])
    // 焦点经过不激活：active 仍是华北营收。
    expect(browser._state.store.active).toBe(browser._state.store.tasks[1].key)
    tabList.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(browser._state.store.active).toBe(browser._state.store.tasks[0].key)
    // 激活后焦点按设计进入对象标题；Delete 前先把焦点移回页签。
    await flush()
    tabs()[1].focus()
    tabList.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }))
    expect(shell.querySelectorAll('.evidence-tab')).toHaveLength(2)
    expect(shell.querySelector('.evidence-tab-name')!.textContent).toBe('华北营收')
  })

  it('closing a background tab keeps the active one; closing the active falls back to MRU', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    browser.openObject(fact('fact-b', '华北营收'))
    await flush()
    // 关闭非当前任务（华东营收）不抢走当前页。
    shell.querySelector<HTMLButtonElement>('.evidence-tab-close')!.click()
    await flush()
    expect(shell.querySelectorAll('.evidence-tab')).toHaveLength(2)
    expect(browser._state.store.active).toBe(browser._state.store.tasks[0].key)
    expect(shell.querySelector('.evidence-tab-name')!.textContent).toBe('华北营收')
    // 关闭当前任务后回到最近使用的仍打开页签。
    shell.querySelector<HTMLButtonElement>('.evidence-tab-close')!.click()
    await flush()
    expect(shell.querySelectorAll('.evidence-tab')).toHaveLength(1)
    expect(browser.isOpen()).toBe(false)
  })

  it('breadcrumb navigation truncates the path and back restores it', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    await flush()
    const state = browser._state
    state.navigate({ kind: 'computation', key: 'comp-1', label: '渠道收入汇总' })
    state.navigate({ kind: 'dataset', key: 'dataset-1', label: '收入明细.csv' })
    browser.open() // 触发 renderAll 反映 state
    await flush()
    expect(shell.querySelector('.evidence-tab-stage')!.textContent).toBe('快照')
    const crumbs = shell.querySelectorAll<HTMLButtonElement>('.evidence-crumb')
    expect([...crumbs].map((crumb) => crumb.textContent)).toEqual(['华东营收', '渠道收入汇总'])
    crumbs[0].click()
    await flush()
    expect(shell.querySelector('.evidence-crumb-current')!.textContent).toBe('华东营收')
    expect(shell.querySelector('.evidence-tab-stage')!.textContent).toBe('事实')
    // 面包屑返回后可以再后退到刚才的深层页面。
    const back = shell.querySelector<HTMLButtonElement>('[data-evidence="back"]')!
    expect(back.disabled).toBe(false)
    back.click()
    await flush()
    expect(shell.querySelector('.evidence-crumb-current')!.textContent).toBe('收入明细.csv')
  })

  it('lists every task without changing the active task until a list item is chosen', async () => {
    const { shell, browser } = setup()
    for (let index = 0; index < 12; index += 1) browser.openObject(fact(`fact-${index}`, `任务 ${index}`))
    await flush()
    const picker = shell.querySelector<HTMLDetailsElement>('.evidence-task-picker')!
    picker.open = true
    const active = browser._state.store.active
    const items = picker.querySelectorAll<HTMLButtonElement>('button')
    expect(items).toHaveLength(14)
    expect(items[1].disabled).toBe(true)
    expect(items[2].textContent).toBe('任务 0 · 事实')
    items[2].focus()
    expect(browser._state.store.active).toBe(active)
    items[2].click()
    await flush()
    expect(browser._state.currentTask()?.root.key).toBe('fact-0')
    expect(picker.open).toBe(false)
    picker.open = true
    picker.querySelector<HTMLButtonElement>('button')!.focus()
    picker.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(picker.open).toBe(false)
    expect(document.activeElement).toBe(picker.querySelector('summary'))
  })

  it('keeps the full long path available and navigates to a folded ancestor', async () => {
    const { shell, browser } = setup()
    browser.openObject(fact('root', '任务起点'))
    for (let index = 0; index < 5; index += 1) browser._state.navigate(fact(`step-${index}`, `对象 ${index}`))
    browser.open()
    await flush()
    const picker = shell.querySelector<HTMLDetailsElement>('.evidence-path-picker')!
    expect(picker.hidden).toBe(false)
    expect(shell.querySelectorAll('.evidence-crumb-folded')).toHaveLength(3)
    const items = picker.querySelectorAll<HTMLButtonElement>('button')
    expect(items).toHaveLength(6)
    expect(items[5].getAttribute('aria-current')).toBe('page')
    expect(items[5].disabled).toBe(true)
    picker.open = true
    items[2].click()
    await flush()
    expect(browser._state.currentPage()?.path.map((ref) => ref.key)).toEqual(['root', 'step-0', 'step-1'])
    expect(picker.open).toBe(false)
    shell.querySelector<HTMLButtonElement>('[data-evidence="back"]')!.click()
    await flush()
    expect(browser._state.currentPage()?.path).toHaveLength(6)
  })

  it('openSubject opens a subject task and announces it', async () => {
    const { shell, browser } = setup()
    await browser.openSubject('sub-aaaa')
    await flush()
    expect(shell.hidden).toBe(false)
    expect(shell.querySelector('.evidence-tab-stage')!.textContent).toBe('引用')
    expect(browser._state.currentPage()?.ref.kind).toBe('subject')
    expect(browser._state.currentPage()?.ref.key).toBe('sub-aaaa')
  })

  it('ignores a late source failure after reset without invalidating the new source cache', async () => {
    const client = makeClient()
    let rejectOld!: (error: Error) => void
    const old = new Promise<TraceSources>((_resolve, reject) => { rejectOld = reject })
    const source = PAYLOADS['/api/sources'] as TraceSources
    const latest = { ...source, datasets: source.datasets!.map(item => ({ ...item, filename: '新修订.csv' })) }
    const sources = vi.spyOn(client, 'sources').mockImplementationOnce(() => old).mockResolvedValue(latest)
    const { browser, shell } = setup(client)
    browser.open()
    browser.reset()
    browser.open()
    await flush()
    await flush()
    expect(shell.querySelector('.evidence-directory-items')?.textContent).toContain('新修订.csv')
    rejectOld(new Error('late failure'))
    await flush()
    await browser.openSubject('sub-aaaa')
    expect(sources).toHaveBeenCalledTimes(2)
    expect(shell.querySelector('.evidence-directory-items')?.textContent).toContain('新修订.csv')
    expect(shell.querySelector('.evidence-directory-items')?.textContent).not.toContain('加载失败')
  })

  it('ignores old directory results and old subject navigation after a revision reset', async () => {
    const client = makeClient()
    let resolveOld!: (sources: TraceSources) => void
    const old = new Promise<TraceSources>(resolve => { resolveOld = resolve })
    const source = PAYLOADS['/api/sources'] as TraceSources
    const sources = vi.spyOn(client, 'sources').mockImplementationOnce(() => old).mockResolvedValue({ ...source, subjects: [] })
    const { browser, shell } = setup(client)
    const opening = browser.openSubject('sub-aaaa')
    browser.reset()
    browser.open()
    await flush()
    resolveOld(source)
    await opening
    await flush()
    expect(browser._state.store.tasks).toHaveLength(0)
    expect(shell.querySelector('.evidence-directory-items')?.textContent).not.toContain('正文引用')
    expect(sources).toHaveBeenCalledTimes(2)
  })

  it('keeps the latest navigation intent when source lookup completes late', async () => {
    const client = makeClient()
    let resolve!: (sources: TraceSources) => void
    vi.spyOn(client, 'sources').mockImplementation(() => new Promise(done => { resolve = done }))
    const { browser } = setup(client)
    const opening = browser.openSubject('sub-aaaa')
    browser.openObject(fact('new-target', '最新选择'))
    resolve(PAYLOADS['/api/sources'] as TraceSources)
    await opening
    expect(browser._state.currentPage()?.ref.key).toBe('new-target')
    expect(browser._state.store.tasks).toHaveLength(1)
  })

  it('reset drops all task state after a revision change', async () => {
    const { shell, browser, onReturnToReport } = setup()
    browser.openObject(fact('fact-a', '华东营收'))
    await flush()
    browser.reset()
    expect(browser._state.store.tasks).toHaveLength(0)
    expect(shell.hidden).toBe(true)
    expect(onReturnToReport).toHaveBeenCalled()
  })
})
