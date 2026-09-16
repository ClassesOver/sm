import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createLocalDraftController } from './draft'

describe('createLocalDraftController', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.innerHTML = '<main id="app"></main>'
  })

  it('offers a different local draft and restores it on request', () => {
    localStorage.setItem('draft-key', '本地内容')
    const restore = vi.fn()
    const controller = createLocalDraftController(
      document.querySelector<HTMLElement>('#app')!,
      'draft-key',
      restore,
    )
    controller.offer('# 服务器内容')
    expect(document.querySelector('.draft-recovery')?.hasAttribute('hidden')).toBe(false)
    document.querySelector<HTMLButtonElement>('[data-draft="restore"]')!.click()
    expect(restore).toHaveBeenCalledWith('本地内容')
  })

  it('stores changes and clears saved drafts', () => {
    const controller = createLocalDraftController(document.body, 'draft-key', vi.fn())
    controller.store('修改内容')
    expect(localStorage.getItem('draft-key')).toBe('修改内容')
    controller.clear()
    expect(localStorage.getItem('draft-key')).toBeNull()
  })
})
