import { describe, expect, it } from 'vitest'
import { computePlayOrder } from './vendor/genoffice/renderer/slideshow-utils'
describe('computePlayOrder (playback order)', () => {
  const slides = [{}, { hidden: true }, {}, {}, { hidden: true }]

  it('default order skips hidden slides', () => {
    expect(computePlayOrder(slides, 0)).toEqual([0, 2, 3])
  })

  it('starting from a hidden slide keeps that slide', () => {
    expect(computePlayOrder(slides, 1)).toEqual([0, 1, 2, 3])
  })

  it('custom show plays in the specified order', () => {
    expect(computePlayOrder(slides, 3, [3, 0, 2])).toEqual([3, 0, 2])
  })

  it('custom show filters out hidden slides and out-of-range indices', () => {
    expect(computePlayOrder(slides, 3, [3, 1, 99, 0])).toEqual([3, 0])
  })

  it('falls back to the starting slide when the result is empty', () => {
    expect(computePlayOrder([{ hidden: true }], 0, [99])).toEqual([0])
  })

  it('returns no order for an out-of-range start slide', () => {
    expect(computePlayOrder([], 0)).toEqual([])
    expect(computePlayOrder([{}, {}], 5)).toEqual([])
    expect(computePlayOrder([{}, {}], -1)).toEqual([])
    expect(computePlayOrder([{}, {}], 1)).toEqual([0, 1])
  })
})

