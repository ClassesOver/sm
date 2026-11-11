import { expect, it, vi } from 'vitest'
import { LifecycleService, LifecycleStages } from '@univerjs/core'
import { IRenderManagerService } from '@univerjs/engine-render'
const path = './workbook-render-ready'
it('waits for native rendered lifecycle and rejects a replaced workbook core', async () => {
  let release!: () => void
  const stage = new Promise<void>(resolve => { release = resolve })
  const lifecycle = { onStage: vi.fn(() => stage) }
  const core = {}, book = { getWorkbook: () => core }
  let active = book
  const runtime = { univer: { __getInjector: () => ({ has: (token: unknown) => token === IRenderManagerService, get: (token: unknown) => token === LifecycleService ? lifecycle : undefined }) }, univerAPI: { getActiveWorkbook: () => active } }
  const { waitForWorkbookRendered } = await import(/* @vite-ignore */path)
  let done = false
  const waiting = waitForWorkbookRendered(runtime, () => false).then(() => { done = true })
  await Promise.resolve()
  expect(done).toBe(false)
  expect(lifecycle.onStage).toHaveBeenCalledWith(LifecycleStages.Rendered)
  active = { getWorkbook: () => ({}) }
  release()
  await expect(waiting).rejects.toThrow('身份')
})
it('supports non-rendering test hosts without requesting a render lifecycle', async () => {
  const { waitForWorkbookRendered } = await import(/* @vite-ignore */path)
  await expect(waitForWorkbookRendered({ univer: {}, univerAPI: {} }, () => false)).resolves.toBeUndefined()
})

it('blocks user input while loading without preventing native focus initialization', async () => {
  const { installWorkbookLoadingLock } = await import(/* @vite-ignore */path)
  const grid = document.createElement('div'), editor = document.createElement('input')
  grid.append(editor); document.body.append(grid)
  let loading = true
  const clicked = vi.fn(), focused = vi.fn()
  editor.addEventListener('click', clicked); editor.addEventListener('focus', focused)
  const lock = installWorkbookLoadingLock(grid, () => loading)
  try {
    editor.focus()
    expect(focused).toHaveBeenCalledOnce()
    expect(grid.inert).not.toBe(true)
    expect(editor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))).toBe(false)
    expect(clicked).not.toHaveBeenCalled()
    loading = false
    editor.click()
    expect(clicked).toHaveBeenCalledOnce()
  } finally { lock.dispose(); grid.remove() }
})
