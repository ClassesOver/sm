import { afterEach, expect, it, vi } from 'vitest'
import { createDocxHfProbeScope } from './docx-hf-probe-scope'
import { hfReservedHeightPx } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom'

afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren() })
it('places new strip measurements inside the mounted document and returns them to the body on release', () => {
  const host = document.createElement('div'); host.className = 'docx-native'; document.body.append(host)
  const release = createDocxHfProbeScope(host)
  hfReservedHeightPx('header', { text: 'scope fixture' }, 600)
  const probe = document.getElementById('hf-strip-probe')!
  expect(probe.parentElement).toBe(host)
  release()
  expect(probe.parentElement).toBe(document.body)
  release()
  expect(probe.parentElement).toBe(document.body)
})
it('restores a foreign probe parent and handles two document lifetimes released out of order', () => {
  const foreign = document.createElement('section'), first = document.createElement('div'), second = document.createElement('div')
  const probe = document.createElement('div'); probe.id = 'hf-strip-probe'; probe.className = 'doc-page'
  foreign.append(probe); document.body.append(foreign, first, second)
  const releaseFirst = createDocxHfProbeScope(first)
  expect(probe.parentElement).toBe(first)
  const releaseSecond = createDocxHfProbeScope(second)
  expect(probe.parentElement).toBe(second)
  releaseFirst()
  expect(probe.parentElement).toBe(second)
  releaseSecond()
  expect(probe.parentElement).toBe(foreign)
})

it('invalidates strip height caches when the active document scope changes', () => {
  const first = document.createElement('div'), second = document.createElement('div')
  first.dataset.height = '40'; second.dataset.height = '75'; document.body.append(first, second)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const height = Number(this.closest('[data-height]')?.getAttribute('data-height') ?? 0)
    return { x: 0, y: this.classList.contains('page-hf-flow-end') ? height : 0, top: this.classList.contains('page-hf-flow-end') ? height : 0, left: 0, right: 600, bottom: height, width: 600, height, toJSON() {} }
  })
  const value = { text: 'identical strip, different document styles' }
  const releaseFirst = createDocxHfProbeScope(first)
  try {
    expect(hfReservedHeightPx('header', value, 600)).toBe(40)
    const releaseSecond = createDocxHfProbeScope(second)
    try { expect(hfReservedHeightPx('header', value, 600)).toBe(75) }
    finally { releaseSecond() }
    expect(hfReservedHeightPx('header', value, 600)).toBe(40)
  } finally { releaseFirst() }
})
