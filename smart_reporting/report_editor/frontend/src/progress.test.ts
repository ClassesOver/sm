import { describe, expect, it, vi } from 'vitest'

import { createBackToTopController, scrollProgress } from './progress'

describe('scrollProgress', () => {
  it('calculates and clamps document progress', () => {
    expect(scrollProgress(500, 2000, 1000)).toBe(50)
    expect(scrollProgress(-10, 2000, 1000)).toBe(0)
    expect(scrollProgress(1500, 2000, 1000)).toBe(100)
  })

  it('returns complete when the page does not scroll', () => {
    expect(scrollProgress(0, 800, 800)).toBe(100)
  })
})

describe('createBackToTopController', () => {
  it('shows after the threshold and scrolls to the top', () => {
    const button = document.createElement('button')
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 700 })
    createBackToTopController(button)
    window.dispatchEvent(new Event('scroll'))
    expect(button.hidden).toBe(false)
    button.click()
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    vi.unstubAllGlobals()
  })
})
