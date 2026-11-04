import { describe, expect, it } from 'vitest'
import * as cjk from 'cjk-regex'
import { precomputedCjkModule } from '../scripts/precomputed-cjk'
import { withWorkbookLocked } from './workbook-grid-guards'

describe('workbook grid guards', () => {
  it.each(['all', 'letters', 'punctuations'] as const)('retains the exact renderer %s regexp', name => {
    const module = new Function(`${precomputedCjkModule().replaceAll('export function', 'function')}; return {all, letters, punctuations}`)()
    expect(module[name]().toRegExp()).toEqual(cjk[name]().toRegExp())
  })
  it('keeps the grid inert from snapshot capture through asynchronous candidate reload', async () => {
    const editor = document.createElement('div')
    editor.inert = false
    let finish!: () => void
    const remote = new Promise<void>(resolve => { finish = resolve })
    let loaded = false
    const accepted = withWorkbookLocked(editor, async () => {
      expect(editor.inert).toBe(true)
      await remote
      expect(editor.inert).toBe(true)
      loaded = true
    })
    expect(editor.inert).toBe(true)
    finish()
    await accepted
    expect(loaded).toBe(true)
    expect(editor.inert).toBe(false)
  })
  it('unlocks the retained draft if server acceptance fails', async () => {
    const editor = document.createElement('div')
    editor.inert = false
    await expect(withWorkbookLocked(editor, async () => { throw Error('offline') })).rejects.toThrow('offline')
    expect(editor.inert).toBe(false)
  })
})
