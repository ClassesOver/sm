import { describe, expect, it } from 'vitest'
import { WorkbookDraft } from './workbook-draft'

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
