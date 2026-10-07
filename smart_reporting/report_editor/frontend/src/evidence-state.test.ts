import { describe, expect, it } from 'vitest'

import {
  createEvidenceState,
  evidenceRefId,
  REPORT_TAB,
  type EvidenceObjectRef,
} from './evidence-state'

const fact = (key: string, label = key): EvidenceObjectRef => ({
  kind: 'fact',
  key,
  analysisId: 'analysis_001',
  label,
})
const computation = (key: string, label = key): EvidenceObjectRef => ({
  kind: 'computation',
  key,
  label,
})
const dataset = (key: string, label = key): EvidenceObjectRef => ({
  kind: 'dataset',
  key,
  label,
})

describe('evidence state', () => {
  it('defaults new pages to 3D and carries the mode through navigation', () => {
    const state = createEvidenceState()
    state.openTask(fact('fact-a'))
    expect(state.currentPage()?.graphMode).toBe('3d')
    state.updatePage({ graphMode: '2d' })
    state.navigate(computation('comp-1'))
    expect(state.currentPage()?.graphMode).toBe('2d')
    state.back()
    expect(state.currentPage()?.graphMode).toBe('2d')
  })

  it('relabels open and closed tasks by identity without touching history', () => {
    const state = createEvidenceState()
    state.openTask(dataset('ds-1'))
    state.navigate(computation('comp-1'))
    state.openTask(computation('comp-2'))
    state.closeTask(state.store.active!)
    const labels: Record<string, string> = { 'ds-1': '收入明细.csv', 'comp-1': '渠道收入汇总', 'comp-2': '成本汇总' }
    expect(state.relabel((ref) => labels[ref.key])).toBe(true)
    const task = state.store.tasks[0]!
    expect(task.root.label).toBe('收入明细.csv')
    expect(task.history.map((page) => page.ref.label)).toEqual(['收入明细.csv', '渠道收入汇总'])
    expect(task.history[1]!.path.map((ref) => ref.label)).toEqual(['收入明细.csv', '渠道收入汇总'])
    expect(task.index).toBe(1)
    expect(state.closedTasks[0]!.root.label).toBe('成本汇总')
    // 再次同步没有变化时返回 false，调用方无需重渲染。
    expect(state.relabel((ref) => labels[ref.key])).toBe(false)
  })

  it('opens a task in the foreground and dedupes by object identity', () => {
    const state = createEvidenceState()
    const task = state.openTask(fact('fact-a', '华东营收'))
    expect(state.store.active).toBe(task.key)
    expect(state.store.tasks).toHaveLength(1)

    const again = state.openTask(fact('fact-a', '华东营收（别名）'))
    expect(again.key).toBe(task.key)
    expect(state.store.tasks).toHaveLength(1)
    expect(state.store.active).toBe(task.key)
    // 名称相同但对象身份不同不能误合并。
    const other = state.openTask(fact('fact-b', '华东营收'))
    expect(other.key).not.toBe(task.key)
    expect(state.store.tasks).toHaveLength(2)
  })

  it('opens a background task without stealing the active tab', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    const background = state.openTask(dataset('dataset-1'), { foreground: false })
    expect(state.store.active).toBe(first.key)
    expect(state.store.tasks.map((task) => task.key)).toEqual([first.key, background.key])
  })

  it('navigates within the current task without creating new tabs', () => {
    const state = createEvidenceState()
    const task = state.openTask(fact('fact-a'))
    state.navigate(computation('comp-1'))
    state.navigate(dataset('dataset-1'))
    expect(state.store.tasks).toHaveLength(1)
    expect(task.history).toHaveLength(3)
    expect(task.index).toBe(2)
    const page = state.currentPage()
    expect(page?.ref.key).toBe('dataset-1')
    expect(page?.path.map((ref) => ref.key)).toEqual(['fact-a', 'comp-1', 'dataset-1'])
    // 所有来源对象首次打开都展开关系区。
    expect(page?.collapsed).toBe(false)
    expect(task.history[0].collapsed).toBe(false)
  })

  it('truncates the path when navigating to an object already on the path', () => {
    const state = createEvidenceState()
    state.openTask(fact('fact-a'))
    state.navigate(computation('comp-1'))
    state.navigate(dataset('dataset-1'))
    const page = state.navigate(fact('fact-a'))
    expect(page?.path.map((ref) => ref.key)).toEqual(['fact-a'])
    expect(state.currentPage()?.ref.key).toBe('fact-a')
  })

  it('does not append history when entering the current page object', () => {
    const state = createEvidenceState()
    const task = state.openTask(fact('fact-a'))
    state.navigate(computation('comp-1'))
    const before = task.history.length
    const page = state.navigate(computation('comp-1'))
    expect(task.history).toHaveLength(before)
    expect(page).toBe(state.currentPage())
  })

  it('back and forward restore per-page state such as the snapshot filter', () => {
    const state = createEvidenceState()
    state.openTask(fact('fact-a'))
    state.navigate(computation('comp-1'))
    state.navigate(dataset('dataset-1'))
    state.updatePage({ filter: '华东' })

    state.back()
    expect(state.currentPage()?.ref.key).toBe('comp-1')
    state.forward()
    expect(state.currentPage()?.ref.key).toBe('dataset-1')
    expect(state.currentPage()?.filter).toBe('华东')
  })

  it('reuses the forward entry for the same object and path instead of resetting state', () => {
    const state = createEvidenceState()
    const task = state.openTask(fact('fact-a'))
    state.navigate(computation('comp-1'))
    state.navigate(dataset('dataset-1'))
    state.updatePage({ filter: '华东', scroll: 120 })

    // 面包屑回到事实是一次导航，会截短路径；之后后退应回到快照页且筛选还在。
    state.navigate(fact('fact-a'))
    expect(state.currentPage()?.ref.key).toBe('fact-a')
    state.back()
    expect(state.currentPage()?.ref.key).toBe('dataset-1')
    expect(state.currentPage()?.filter).toBe('华东')
    expect(state.currentPage()?.scroll).toBe(120)

    // 从深层页面前进分支仍存在时，导航到同对象同路径复用而不是新建。
    state.back()
    state.back()
    state.navigate(computation('comp-1'))
    state.navigate(dataset('dataset-1'))
    expect(state.currentPage()?.filter).toBe('华东')
    expect(task.history.filter((page) => page.ref.key === 'dataset-1')).toHaveLength(1)
  })

  it('drops only the current task forward branch on a fresh navigation', () => {
    const state = createEvidenceState()
    const task = state.openTask(fact('fact-a'))
    state.navigate(computation('comp-1'))
    state.back()
    state.navigate(dataset('dataset-2'))
    expect(task.history.map((page) => page.ref.key)).toEqual(['fact-a', 'dataset-2'])
    expect(state.forward()).toBeNull()
  })

  it('keeps filters independent between tasks', () => {
    const state = createEvidenceState()
    const east = state.openTask(fact('fact-east', '华东营收'))
    state.navigate(dataset('dataset-1'))
    state.updatePage({ filter: '华东' })
    const north = state.openTask(fact('fact-north', '华北营收'))
    state.navigate(dataset('dataset-1'))
    state.updatePage({ filter: '华北' })

    state.switchTask(east.key)
    expect(state.currentPage()?.filter).toBe('华东')
    state.switchTask(north.key)
    expect(state.currentPage()?.filter).toBe('华北')
  })

  it('closing a background task never steals the active tab', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    const second = state.openTask(computation('comp-1'), { foreground: false })
    state.closeTask(second.key)
    expect(state.store.active).toBe(first.key)
    expect(state.store.tasks).toHaveLength(1)
  })

  it('reopening an existing task in the background preserves the active task', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    const second = state.openTask(computation('comp-1'))
    state.openTask(first.root, { foreground: false })
    expect(state.store.active).toBe(second.key)
    expect(state.store.tasks).toHaveLength(2)
  })

  it('reorders tasks without changing the active task', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    const second = state.openTask(computation('comp-1'))
    const third = state.openTask(dataset('dataset-1'))
    state.reorderTask(third.key, 0)
    expect(state.store.tasks.map((task) => task.key)).toEqual([third.key, first.key, second.key])
    expect(state.store.active).toBe(third.key)
  })

  it('closing the active task falls back to the most recently used task, then report', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    const second = state.openTask(computation('comp-1'))
    state.switchTask(first.key)
    state.switchTask(second.key)
    state.closeTask(second.key)
    expect(state.store.active).toBe(first.key)
    state.closeTask(first.key)
    expect(state.store.active).toBe(REPORT_TAB)
  })

  it('preview selection changes only page state, not path, history or tabs', () => {
    const state = createEvidenceState()
    const task = state.openTask(fact('fact-a'))
    const historyBefore = task.history.length
    state.updatePage({ selected: computation('comp-1', '渠道收入汇总') })
    expect(task.history).toHaveLength(historyBefore)
    expect(state.currentPage()?.path.map((ref) => ref.key)).toEqual(['fact-a'])
    expect(state.currentPage()?.selected?.key).toBe('comp-1')
    expect(state.store.tasks).toHaveLength(1)
  })

  it('restores closed tasks in reverse order with their page scene and forward history', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    state.navigate(dataset('dataset-1'))
    state.updatePage({ filter: '华东', datasetCursors: [null, 'page-2'], datasetPageIndex: 1 })
    state.back()
    const second = state.openTask(computation('comp-1'))
    state.closeTask(first.key)
    state.closeTask(second.key)
    expect(state.restoreTask()).toBe(second)
    expect(state.restoreTask()).toBe(first)
    expect(state.store.active).toBe(first.key)
    state.forward()
    expect(state.currentPage()?.filter).toBe('华东')
    expect(state.currentPage()?.datasetPageIndex).toBe(1)
    expect(state.restoreTask()).toBeNull()
  })

  it('restoring a closed root that was reopened activates its existing task without duplicates', () => {
    const state = createEvidenceState()
    const first = state.openTask(fact('fact-a'))
    state.closeTask(first.key)
    const reopened = state.openTask(first.root)
    state.updatePage({ filter: '新现场' })
    expect(state.restoreTask()).toBe(reopened)
    expect(state.store.tasks).toHaveLength(1)
    expect(state.currentPage()?.filter).toBe('新现场')
  })

  it('restores an ancestor page scene without mutating its older history entry', () => {
    const state = createEvidenceState()
    state.openTask(fact('root'))
    state.navigate(dataset('rows'))
    const earlier = state.currentPage()!
    state.updatePage({
      datasetCursors: [null, 'cursor-2'], datasetPageIndex: 1,
      columnWidths: { branch: 184 }, tableScroll: 60, filter: '华北',
    })
    state.navigate(computation('sum'))
    state.navigate(dataset('rows'))
    const restored = state.currentPage()!
    expect(restored).not.toBe(earlier)
    expect(restored.datasetPageIndex).toBe(1)
    expect(restored.filter).toBe('华北')
    expect(restored.tableScroll).toBe(60)
    expect(restored.columnWidths.branch).toBe(184)
    restored.columnWidths.branch = 200
    restored.datasetCursors.push('cursor-3')
    expect(earlier.columnWidths.branch).toBe(184)
    expect(earlier.datasetCursors).toEqual([null, 'cursor-2'])
  })

  it('computes stable object identity including type and analysis scope', () => {
    expect(evidenceRefId(fact('fact-a'))).toBe('fact:analysis_001/fact-a')
    expect(evidenceRefId({ kind: 'fact', key: 'fact-a', analysisId: 'analysis_002', label: 'x' }))
      .toBe('fact:analysis_002/fact-a')
    expect(evidenceRefId(dataset('fact-a'))).toBe('dataset:fact-a')
  })
})
