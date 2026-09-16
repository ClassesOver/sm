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
    controller.clear()
    expect(localStorage.getItem('draft-key')).toBeNull()
  })

  it('debounces rapid keystroke stores into one write', () => {
    vi.useFakeTimers()
    try {
      const controller = createLocalDraftController(document.body, 'draft-key', vi.fn())
      controller.store('a')
      controller.store('ab')
      controller.store('abc')
      expect(localStorage.getItem('draft-key')).toBeNull()

      vi.advanceTimersByTime(2000)

      expect(localStorage.getItem('draft-key')).toBe('abc')
    } finally {
      vi.useRealTimers()
    }
  })

  it('flushes a pending draft store before unload', () => {
    vi.useFakeTimers()
    try {
      const controller = createLocalDraftController(document.body, 'draft-key', vi.fn())
      controller.store('pending')
      window.dispatchEvent(new Event('beforeunload'))

      expect(localStorage.getItem('draft-key')).toBe('pending')
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps editing usable when localStorage quota is exhausted', () => {
    vi.useFakeTimers()
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota exceeded', 'QuotaExceededError')
    })
    try {
      const controller = createLocalDraftController(document.body, 'draft-key', vi.fn())
      controller.store('large draft')

      expect(() => vi.advanceTimersByTime(2000)).not.toThrow()
      expect(() => window.dispatchEvent(new Event('beforeunload'))).not.toThrow()
    } finally {
      setItem.mockRestore()
      vi.useRealTimers()
    }
  })

  it('does not block loading when localStorage reads are unavailable', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    try {
      const controller = createLocalDraftController(document.body, 'draft-key', vi.fn())

      expect(() => controller.offer('# server')).not.toThrow()
      expect(controller.banner.hidden).toBe(true)
    } finally {
      getItem.mockRestore()
    }
  })

  it('does not block discarding when localStorage removal is unavailable', () => {
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    try {
      const controller = createLocalDraftController(document.body, 'draft-key', vi.fn())
      controller.banner.hidden = false

      expect(() =>
        controller.banner.querySelector<HTMLButtonElement>('[data-draft="discard"]')!.click(),
      ).not.toThrow()
      expect(controller.banner.hidden).toBe(true)
    } finally {
      removeItem.mockRestore()
    }
  })
})
