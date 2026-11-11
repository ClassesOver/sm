import { expect, it } from 'vitest'
import { planSlidesArrange, type SlidesArrangeOp, type SlidesArrangeSlide } from './slides-arrange'

const geometry = (x: number, y: number, width = 20, height = 10) => ({ x, y, width, height })
const slide: SlidesArrangeSlide = { slideIndex: 0, widthPx: 960, heightPx: 540, elements: [
  { id: 'a', type: 'text', arrangeEditable: true, geometry: geometry(10, 20) },
  { id: 'b', type: 'shape', arrangeEditable: true, geometry: geometry(100, 80, 40, 30) },
  { id: 'c', type: 'picture', arrangeEditable: true, geometry: geometry(200, 140, 60, 50) },
] }

it.each<[SlidesArrangeOp, number[], number[]]>([
  ['left', [10, 10, 10], [20, 80, 140]], ['center-h', [125, 115, 105], [20, 80, 140]],
  ['right', [240, 220, 200], [20, 80, 140]], ['top', [10, 100, 200], [20, 20, 20]],
  ['center-v', [10, 100, 200], [100, 90, 80]], ['bottom', [10, 100, 200], [180, 160, 140]],
  ['distribute-h', [10, 95, 200], [20, 80, 140]], ['distribute-v', [10, 100, 200], [20, 70, 140]],
])('uses source geometry helper for %s without changing dimensions or unrelated edits', (op, xs, ys) => {
  const edits = [{ slideIndex: 0, elementId: 'a', text: 'pending words' }, { slideIndex: 1, elementId: 'other', text: 'untouched' }]
  const plan = planSlidesArrange(slide, ['a', 'b', 'c'], edits, op)
  const merged = new Map(plan.edits.map(edit => [edit.elementId, edit]))
  for (const [index, source] of slide.elements.entries()) {
    const frame = merged.get(source.id)?.geometry ?? source.geometry!
    expect(frame).toEqual({ ...source.geometry, x: xs[index], y: ys[index] })
  }
  expect(merged.get('a')!.text).toBe('pending words')
  expect(merged.get('other')).toEqual(edits[1])
  expect(edits[0]).not.toHaveProperty('geometry')
})

it('uses pending frame before crop frame before source; single selection aligns to the original page', () => {
  const crop = new Map([['a', geometry(30, 35, 30, 20)], ['b', geometry(150, 100, 50, 40)]])
  const plan = planSlidesArrange(slide, ['a', 'b'], [{ slideIndex: 0, elementId: 'a', geometry: geometry(25, 30, 25, 15) }], 'right', crop)
  expect(plan.edits[0]!.geometry).toEqual(geometry(175, 30, 25, 15))
  expect(planSlidesArrange(slide, ['a'], [], 'center-h', crop).edits[0]!.geometry).toEqual(geometry(465, 35, 30, 20))
})

it('returns zero moves for already aligned selections and rejects unsafe batches without mutation', () => {
  expect(planSlidesArrange(slide, ['a'], [], 'left').count).toBe(1)
  const aligned = { ...slide, elements: slide.elements.map(element => ({ ...element, geometry: { ...element.geometry!, x: 10 } })) }
  expect(planSlidesArrange(aligned, ['a', 'b'], [], 'left')).toEqual({ edits: [], count: 0 })
  for (const ids of [[], ['a', 'a'], ['a', 'missing'], Array.from({ length: 501 }, (_, index) => String(index))]) {
    expect(() => planSlidesArrange(slide, ids, [], 'left')).toThrow()
  }
  expect(() => planSlidesArrange(slide, ['a', 'b'], [], 'distribute-h')).toThrow()
  for (const element of [
    { ...slide.elements[1]!, arrangeEditable: false }, { ...slide.elements[1]!, type: 'group' },
    { ...slide.elements[1]!, arrangeEditable: 'yes' as unknown as boolean },
    { ...slide.elements[1]!, geometry: geometry(NaN, 10) }, { ...slide.elements[1]!, geometry: geometry(1, 1, 0) },
  ]) expect(() => planSlidesArrange({ ...slide, elements: [slide.elements[0]!, element] }, ['a', 'b'], [], 'left')).toThrow()
  const overlap = { ...slide, elements: [
    { ...slide.elements[0]!, geometry: geometry(0, 0, 1) },
    { ...slide.elements[1]!, geometry: geometry(1, 0, 1000) },
    { ...slide.elements[2]!, geometry: geometry(2, 0, 1) },
  ] }
  expect(() => planSlidesArrange(overlap, ['a', 'b', 'c'], [], 'distribute-h')).toThrow()
})

it('rejects nonfinite pages and oversized output before returning a plan, and avoids sub-EMU history noise', () => {
  expect(() => planSlidesArrange({ ...slide, widthPx: Infinity }, ['a'], [], 'left')).toThrow()
  const existing = Array.from({ length: 500 }, (_, index) => ({ slideIndex: 1, elementId: String(index), text: 'keep' }))
  expect(() => planSlidesArrange(slide, ['a'], existing, 'left')).toThrow('超限')
  expect(existing).toHaveLength(500)
  const nearlyLeft = { ...slide, elements: [{ ...slide.elements[0]!, geometry: geometry(1e-8, 20) }] }
  expect(planSlidesArrange(nearlyLeft, ['a'], [], 'left')).toEqual({ edits: [], count: 0 })
})
