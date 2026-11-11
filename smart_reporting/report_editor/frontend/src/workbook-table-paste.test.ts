import { expect, it } from 'vitest'
import { followTableHeaderPaste } from './workbook-table-paste'

function service(initial: any[]) {
  const hooks = [...initial]
  return {
    getClipboardHooks: () => hooks,
    addClipboardHook(hook: any) {
      hooks.push(hook); hooks.sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0))
      return { dispose() { hooks.splice(hooks.indexOf(hook), 1) } }
    },
  }
}
function paste(clipboard: ReturnType<typeof service>, method = 'onPasteCells') {
  const hooks = clipboard.getClipboardHooks()
  hooks.forEach(hook => hook.onBeforePaste?.())
  return hooks.flatMap(hook => hook[method]?.()?.redos ?? [])
}
it('plans all hook writes together after generation, restoring callbacks on dispose', () => {
  const first = { id: 'first', marker: 1, onPasteCells() { expect(this.marker).toBe(1); return { redos: [{ id: 'first-write' }], undos: [{ id: 'first-undo' }] } } }
  const second = { id: 'second', onPasteCells: () => ({ redos: [{ id: 'second-write' }], undos: [{ id: 'second-undo' }] }) }
  const original = first.onPasteCells, clipboard = service([first, second])
  let calls = 0
  const dispose = followTableHeaderPaste(clipboard, batch => {
    calls++
    expect(batch.redos).toEqual([{ id: 'first-write' }, { id: 'second-write' }])
    expect(batch.undos).toEqual([{ id: 'first-undo' }, { id: 'second-undo' }])
    return { redos: [{ id: 'follow-all' }], undos: [{ id: 'restore-all' }] }
  })
  expect(paste(clipboard)).toEqual([{ id: 'first-write' }, { id: 'second-write' }, { id: 'follow-all' }])
  expect(calls).toBe(1)
  dispose()
  expect(first.onPasteCells).toBe(original)
  expect(clipboard.getClipboardHooks()).toEqual([first, second])
})
it('resets previous paste batches for plain text and keeps follower undo last', () => {
  const clipboard = service([{ id: 'text', onPastePlainText: () => ({ redos: [{ id: 'text' }], undos: [{ id: 'old-text' }] }) }])
  const dispose = followTableHeaderPaste(clipboard, batch => {
    expect(batch.redos).toHaveLength(1)
    return { redos: [{ id: 'rename' }], undos: [{ id: 'old-column' }] }
  })
  expect(paste(clipboard, 'onPastePlainText')).toEqual([{ id: 'text' }, { id: 'rename' }])
  expect(paste(clipboard, 'onPastePlainText')).toEqual([{ id: 'text' }, { id: 'rename' }])
  const final = clipboard.getClipboardHooks().at(-1).onPastePlainText()
  expect(final.undos).toEqual([{ id: 'old-column' }])
  dispose()
})

it('returns false and reports owned plan rejection at public paste boundaries without executing any mutation', async () => {
  const clipboard = Object.assign(service([{ id: 'text', onPastePlainText: () => ({ redos: [{ id: 'write' }], undos: [] }) }]), {
    marker: 'keep', executed: [] as any[],
    async legacyPaste() { expect(this.marker).toBe('keep'); this.executed.push(...paste(clipboard, 'onPastePlainText')); return true },
    rePasteWithPasteType() { this.executed.push(...paste(clipboard, 'onPastePlainText')); return true },
    async pasteByCopyId() { throw new Error('Unrelated clipboard failure') },
  })
  const original = clipboard.legacyPaste, errors: string[] = []
  let reject = true
  const dispose = followTableHeaderPaste(clipboard, () => { if (reject) throw new Error('透视缓存仍引用'); return { redos: [], undos: [] } }, message => errors.push(message))
  await expect(clipboard.legacyPaste()).resolves.toBe(false)
  expect(clipboard.rePasteWithPasteType()).toBe(false)
  expect(clipboard.executed).toEqual([])
  expect(errors).toEqual(['透视缓存仍引用', '透视缓存仍引用'])
  await expect(clipboard.pasteByCopyId()).rejects.toThrow('Unrelated clipboard failure')
  reject = false
  await expect(clipboard.legacyPaste()).resolves.toBe(true)
  expect(clipboard.executed).toEqual([{ id: 'write' }])
  dispose(); expect(clipboard.legacyPaste).toBe(original)
})

it('restores a previous successful paste when native re-paste undoes it before rejecting the new plan', () => {
  const clipboard = Object.assign(service([{ id: 'text', onPastePlainText: () => ({ redos: [{ id: 'write' }], undos: [] }) }]), {
    format: 'pasted', undo: true, redo: false,
    rePasteWithPasteType() { this.format = 'original'; this.undo = false; this.redo = true; paste(clipboard, 'onPastePlainText'); return true },
  })
  const dispose = followTableHeaderPaste(clipboard, () => { throw new Error('透视缓存仍引用') }, () => {
    expect(clipboard.format).toBe('pasted'); expect(clipboard.undo).toBe(true); expect(clipboard.redo).toBe(false)
  }, () => {
    const before = { format: clipboard.format, undo: clipboard.undo, redo: clipboard.redo }
    return () => Object.assign(clipboard, before)
  })
  expect(clipboard.rePasteWithPasteType()).toBe(false)
  expect(clipboard.format).toBe('pasted'); expect(clipboard.undo).toBe(true); expect(clipboard.redo).toBe(false)
  dispose()
})
