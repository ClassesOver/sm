import { describe, expect, it } from 'vitest'

import { createSaveStateTracker } from './save-state'

describe('save state tracker', () => {
  it('counts distinct edits since the last successful save', () => {
    const tracker = createSaveStateTracker('# 初始\n')

    tracker.edit('# 第一次\n')
    tracker.edit('# 第二次\n')
    tracker.edit('# 第二次\n')

    expect(tracker.pendingChanges).toBe(2)
    expect(tracker.hasUnsavedChanges).toBe(true)
    expect(tracker.dirtyLabel(false)).toBe('有未保存更改 · 2 次编辑待同步')
    expect(tracker.dirtyLabel(true)).toBe('离线 · 2 次编辑待同步')
  })

  it('clears pending edits only when the current document was saved', () => {
    const tracker = createSaveStateTracker('# 初始\n')
    tracker.edit('# 保存目标\n')
    tracker.beginSave()
    tracker.edit('# 保存期间继续编辑\n')

    tracker.saved('# 保存目标\n')

    expect(tracker.pendingChanges).toBe(1)
    expect(tracker.hasUnsavedChanges).toBe(true)
    expect(tracker.shouldWarnBeforeUnload).toBe(true)
  })

  it('records the last saved time and removes the leave warning after save', () => {
    const tracker = createSaveStateTracker(
      '# 初始\n',
      () => new Date('2026-09-16T08:30:00+08:00'),
    )
    tracker.edit('# 修订\n')
    tracker.beginSave()

    tracker.saved('# 修订\n')

    expect(tracker.pendingChanges).toBe(0)
    expect(tracker.hasUnsavedChanges).toBe(false)
    expect(tracker.shouldWarnBeforeUnload).toBe(false)
    expect(tracker.savedLabel()).toContain('已保存')
  })
})
