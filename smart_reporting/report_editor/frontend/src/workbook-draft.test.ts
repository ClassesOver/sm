import { describe, expect, it } from 'vitest'
import { WorkbookDraft, workbookSaveOutcome } from './workbook-draft'

describe('workbook draft candidate identity', () => {
  it('preserves manual edits through preview rejection and rejects stale acceptance', () => {
    const draft = new WorkbookDraft()
    const manual = [{ kind: 'applyCellEdits', edits: [{ cell: { value: 12 } }] }]
    draft.setOperations(manual)
    draft.preview({ summary: '更新', operations: [{ kind: 'applyCellEdits', edits: [{ cell: { value: 20 } }] }] })
    draft.reject()
    expect(draft.operations).toEqual(manual)
    draft.preview({ summary: '更新', operations: [{ kind: 'applyCellEdits', edits: [] }] })
    draft.setOperations([{ kind: 'applyCellEdits', edits: [{ cell: { value: 99 } }] }])
    expect(() => draft.accept()).toThrow('变化')
  })
  it('applies a candidate into the draft and undoes only the accepted candidate', () => {
    const draft = new WorkbookDraft()
    const manual = [{ kind: 'applyCellEdits', edits: [{ cell: { value: 12 } }] }]
    draft.setOperations(manual)
    draft.preview({ summary: '更新', operations: [{ kind: 'applyCellEdits', edits: [{ cell: { value: 20 } }] }] })
    draft.accept()
    expect(draft.operations).toHaveLength(2)
    draft.undo()
    expect(draft.operations).toEqual(manual)
  })
})

describe('workbookSaveOutcome', () => {
  it('reopens the new revision when its editor link was issued', () => {
    expect(workbookSaveOutcome({ revision: 3, revisionRegistered: true, editor: { openUrl: '/open/r3' } }))
      .toEqual({ kind: 'reopen', url: '/open/r3', status: '已保存修订 3' })
  })

  it('stops editing the old base when the revision is registered without an editor link', () => {
    const outcome = workbookSaveOutcome({ revision: 3, revisionRegistered: true })
    expect(outcome.kind).toBe('locked')
    expect(outcome.status).toContain('已保存修订 3')
  })

  it('keeps the draft for retry only when the saved file was not registered as a revision', () => {
    expect(workbookSaveOutcome({ revision: 3, revisionRegistered: false }).kind).toBe('retry')
  })
})
