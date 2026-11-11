import { afterEach, expect, it, vi } from 'vitest'
import { measureCurrentDocxPagination } from './docx-measure-current-pagination'
import * as snapshots from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'
import type { SectionSettings } from '@genoffice/docx-engine'

const fontsDescriptor = Object.getOwnPropertyDescriptor(document, 'fonts')
afterEach(() => {
  vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.replaceChildren()
  if (fontsDescriptor) Object.defineProperty(document, 'fonts', fontsDescriptor)
  else Reflect.deleteProperty(document, 'fonts')
})
const section: SectionSettings = { pageWidth: 3000, pageHeight: 1500, orientation: 'portrait', marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0, pageBorder: false, columns: 1 }
function input() {
  const pm = document.createElement('div'); document.body.append(pm)
  return { pm, section, sections: [], canvasTop: 0, colMode: 'none' as const, colFlow: null, hfParts: {}, hf: { header: null, footer: null, headerFirst: null, footerFirst: null, headerEven: null, footerEven: null, titlePg: false, evenOddHf: false } }
}

it('awaits fonts, current image decode and a frame before returning real source cuts', async () => {
  const facts = input(), events: string[] = []
  const img = document.createElement('img'); img.src = 'test.png'; img.decode = async () => { events.push('image') }; facts.pm.append(img)
  Object.defineProperty(document, 'fonts', { configurable: true, value: { ready: Promise.resolve().then(() => { events.push('fonts') }) } })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { events.push('frame'); callback(0); return 1 })
  const result = await measureCurrentDocxPagination(facts, () => true)
  expect(events).toEqual(['fonts', 'image', 'frame'])
  expect(Array.isArray(result.blocks)).toBe(true)
  expect(result.cuts).toHaveLength(1)
  expect(result.cuts[0]!.pageNo).toBe(1)
})

it('rejects an already obsolete request without decoding or scheduling a frame', async () => {
  const frame = vi.fn(); vi.stubGlobal('requestAnimationFrame', frame)
  await expect(measureCurrentDocxPagination(input(), () => false)).rejects.toThrow('发生变化')
  expect(frame).not.toHaveBeenCalled()
})

it('rejects changed document state after waiting for fonts', async () => {
  let release!: () => void, current = true
  Object.defineProperty(document, 'fonts', { configurable: true, value: { ready: new Promise<void>(resolve => { release = resolve }) } })
  const pending = measureCurrentDocxPagination(input(), () => current)
  current = false; release()
  await expect(pending).rejects.toThrow('发生变化')
})

it('rejects disconnected hosts after the animation frame instead of returning late cuts', async () => {
  const facts = input()
  Object.defineProperty(document, 'fonts', { configurable: true, value: { ready: Promise.resolve() } })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { facts.pm.remove(); callback(0); return 1 })
  await expect(measureCurrentDocxPagination(facts, () => true)).rejects.toThrow('发生变化')
})

it('rejects changed HF state while an image is decoding before scheduling the frame', async () => {
  const facts = input(), frame = vi.fn(); let current = true
  Object.defineProperty(document, 'fonts', { configurable: true, value: { ready: Promise.resolve() } })
  const image = document.createElement('img'); image.decode = async () => { current = false }; facts.pm.append(image)
  vi.stubGlobal('requestAnimationFrame', frame)
  await expect(measureCurrentDocxPagination(facts, () => current)).rejects.toThrow('发生变化')
  expect(frame).not.toHaveBeenCalled()
})

it.each([false, true])('measures PM zoom at one and restores it after failure=%s', async fail => {
  const facts = input(), original = snapshots.withMeasuredPaginationSnapshot
  facts.pm.style.zoom = '1.5'
  Object.defineProperty(document, 'fonts', { configurable: true, value: { ready: Promise.resolve() } })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
  const probe = vi.spyOn(snapshots, 'withMeasuredPaginationSnapshot').mockImplementation((measurement, consume) => {
    expect(facts.pm.style.zoom).toBe('1')
    if (fail) throw new Error('measurement fails')
    return original(measurement, consume)
  })
  try {
    if (fail) await expect(measureCurrentDocxPagination(facts, () => true)).rejects.toThrow('measurement fails')
    else await measureCurrentDocxPagination(facts, () => true)
    expect(probe).toHaveBeenCalledOnce()
    expect(facts.pm.style.zoom).toBe('1.5')
  } finally { probe.mockRestore() }
})
