import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createSearchController } from './search'

describe('createSearchController', () => {
  let root: HTMLElement
  let markdown: string
  let replaceText: (text: string) => void

  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>'
    root = document.querySelector<HTMLElement>('#app')!
    markdown = '收入\n收入\n[[section:finance]]'
    replaceText = (text) => {
      markdown = text
    }
  })

  it('shows match count and cycles through matches', () => {
    const controller = createSearchController({ root, getText: () => markdown, replaceText })
    controller.open()
    const query = root.querySelector<HTMLInputElement>('.search-query')!
    const count = root.querySelector<HTMLElement>('.search-count')!
    query.value = '收入'
    query.dispatchEvent(new Event('input'))

    expect(count.textContent).toBe('1 / 2 个匹配')
    root.querySelector<HTMLButtonElement>('[data-search="next"]')!.click()
    expect(count.textContent).toBe('2 / 2 个匹配')
    root.querySelector<HTMLButtonElement>('[data-search="prev"]')!.click()
    expect(count.textContent).toBe('1 / 2 个匹配')
  })

  it('replaces the current match and all remaining matches', () => {
    const controller = createSearchController({ root, getText: () => markdown, replaceText })
    controller.open()
    const query = root.querySelector<HTMLInputElement>('.search-query')!
    const replacement = root.querySelector<HTMLInputElement>('.search-replacement')!
    query.value = '收入'
    replacement.value = '支出'
    query.dispatchEvent(new Event('input'))
    root.querySelector<HTMLButtonElement>('[data-search="replace"]')!.click()
    expect(markdown).toBe('支出\n收入\n[[section:finance]]')
    root.querySelector<HTMLButtonElement>('[data-search="all"]')!.click()
    expect(markdown).toBe('支出\n支出\n[[section:finance]]')
  })

  it('does not replace protected protocol markers and can close', () => {
    const controller = createSearchController({ root, getText: () => markdown, replaceText })
    controller.open()
    const query = root.querySelector<HTMLInputElement>('.search-query')!
    const replacement = root.querySelector<HTMLInputElement>('.search-replacement')!
    query.value = 'finance'
    replacement.value = 'changed'
    query.dispatchEvent(new Event('input'))
    root.querySelector<HTMLButtonElement>('[data-search="all"]')!.click()
    expect(markdown).toBe('收入\n收入\n[[section:finance]]')
    root.querySelector<HTMLButtonElement>('[data-search="close"]')!.click()
    expect(controller.panel.hidden).toBe(true)
  })

  it('supports familiar search keyboard shortcuts', () => {
    const controller = createSearchController({ root, getText: () => markdown, replaceText })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', ctrlKey: true }))
    const query = root.querySelector<HTMLInputElement>('.search-query')!
    query.value = '收入'
    query.dispatchEvent(new Event('input'))
    query.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(root.querySelector('.search-count')?.textContent).toBe('2 / 2 个匹配')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(controller.panel.hidden).toBe(true)
  })

  it('places the search panel below the sticky toolbar metadata', () => {
    root.innerHTML = '<header class="app-bar"></header><div class="report-meta"></div><div class="report-workspace"></div>'

    const controller = createSearchController({ root, getText: () => markdown, replaceText })

    expect(controller.panel.previousElementSibling?.className).toBe('report-meta')
    expect(controller.panel.nextElementSibling?.className).toBe('report-workspace')
  })

  it('delegates highlight and active-result navigation to the editor search plugin', () => {
    const setQuery = vi.fn()
    const navigate = vi.fn()
    const controller = createSearchController({ root, getText: () => markdown, replaceText, setQuery, navigate })
    controller.open()
    const query = root.querySelector<HTMLInputElement>('.search-query')!
    query.value = '收入'
    query.dispatchEvent(new Event('input'))
    expect(setQuery).toHaveBeenCalledWith('收入', '')
    root.querySelector<HTMLButtonElement>('[data-search="next"]')!.click()
    expect(navigate).toHaveBeenCalledWith('next')
  })
})
