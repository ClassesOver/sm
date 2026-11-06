import { expect, it } from 'vitest'
import { capturePdfZoomAnchor, restorePdfZoomAnchor, stepPdfZoom, clampPdfZoom } from './pdf-view-state'

it('uses pinned adjacent steps and epsilon for fit-derived values rather than multiplication', () => {
  expect(stepPdfZoom(.68, 1)).toBe(.8)
  expect(stepPdfZoom(1.35, 1)).toBe(1.5)
  expect(stepPdfZoom(1.35, -1)).toBe(1.25)
  expect(stepPdfZoom(.9995, 1)).toBe(1.1)
  expect(stepPdfZoom(1.0005, -1)).toBe(.9)
  expect(stepPdfZoom(.1, -1)).toBe(.1)
  expect(stepPdfZoom(8, 1)).toBe(8)
  expect(clampPdfZoom(20)).toBe(8); expect(clampPdfZoom(.01)).toBe(.1)
  expect(() => clampPdfZoom(NaN)).toThrow()
})
function fixture() {
  document.body.innerHTML = '<div id="viewport"><section class="pdf-page" data-page-id="a"><div class="pdf-page-content"></div></section><section class="pdf-page" data-page-id="b"><div class="pdf-page-content"></div></section></div>'
  const viewport = document.querySelector<HTMLElement>('#viewport')!, contents = [...viewport.querySelectorAll<HTMLElement>('.pdf-page-content')]
  let scale = 1, spread = false
  viewport.getBoundingClientRect = () => new DOMRect(20, 100, 600, 500)
  contents.forEach((node, i) => { node.getBoundingClientRect = () => new DOMRect(48 + (spread ? i * (300 * scale + 16) : 0) - viewport.scrollLeft, 140 + (!spread ? i * (400 * scale + 60) : 0) - viewport.scrollTop, 300 * scale, 400 * scale) })
  return { viewport, contents, scale: (value: number) => { scale = value }, spread: () => { spread = true } }
}
it('retains a content point through zoom when native headings and gaps do not scale', () => {
  const f = fixture(); f.viewport.scrollTop = 250
  const anchor = capturePdfZoomAnchor(f.viewport, 1)!
  expect(anchor).toMatchObject({ pageId: 'a', y: 210, vy: 0 })
  f.scale(2); f.viewport.scrollTop = 0
  restorePdfZoomAnchor(f.viewport, anchor, 2)
  expect(f.viewport.scrollTop).toBe(460)
  expect(f.contents[0].getBoundingClientRect().top + anchor.y * 2).toBe(100)
})
it('retains fixed whitespace above the first page instead of scaling its heading', () => {
  const f = fixture(), anchor = capturePdfZoomAnchor(f.viewport, 1)!
  expect(anchor.y).toBe(0); expect(anchor.vy).toBe(40)
  f.scale(2); restorePdfZoomAnchor(f.viewport, anchor, 2)
  expect(f.viewport.scrollTop).toBe(0)
})
it('anchors the spread page under the wheel cursor with an unscaled gutter', () => {
  const f = fixture(); f.spread()
  const anchor = capturePdfZoomAnchor(f.viewport, 1, 450, 120)!
  expect(anchor.pageId).toBe('b')
  f.scale(2); restorePdfZoomAnchor(f.viewport, anchor, 2)
  const box = f.contents[1].getBoundingClientRect()
  expect(box.left + anchor.x * 2).toBe(470)
  expect(box.top + anchor.y * 2).toBe(220)
})
it('ignores stale removed pages and empty layouts without changing scroll', () => {
  const f = fixture(); f.viewport.scrollTop = 75
  restorePdfZoomAnchor(f.viewport, { pageId: 'missing', x: 1, y: 1, vx: 0, vy: 0 }, 2)
  expect(f.viewport.scrollTop).toBe(75)
  f.viewport.replaceChildren(); expect(capturePdfZoomAnchor(f.viewport, 1)).toBeNull()
})
