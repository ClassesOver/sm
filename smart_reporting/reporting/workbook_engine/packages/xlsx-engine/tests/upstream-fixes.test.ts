import { describe, expect, it } from 'vitest'

import { groupValue, parseDateParts } from '../src/pivot-grouping'
import { buildPivotLayout, type PivotScalar } from '../src/pivot-layout'
import { computeSortedRowOrder } from '../src/sort-range'

describe('selective GenOffice upstream fixes', () => {
  it('groups early Excel serial dates around the phantom 1900 leap day', () => {
    for (const serial of [1, 1.75, 31]) {
      expect(parseDateParts(serial)).toEqual({ year: 1900, month: 1 })
    }
    for (const serial of [32, 59, 59.999, 60]) {
      expect(parseDateParts(serial)).toEqual({ year: 1900, month: 2 })
    }
    expect(parseDateParts(61)).toEqual({ year: 1900, month: 3 })
    expect(parseDateParts(45292)).toEqual({ year: 2024, month: 1 })
    expect(groupValue({ kind: 'date', dateUnit: 'month' }, 1)).toEqual({ label: 'Jan', sort: 1 })
  })

  it.each([
    ['sum', 150], ['average', 75], ['min', 50], ['max', 100], ['count', 3],
  ] as const)('includes text-formatted numbers in baked pivot %s', (agg, expected) => {
    const grid: PivotScalar[][] = [
      ['Region', 'Amount'], ['East', '100'], ['West', ' 50 '],
      ['East', 'n/a'], ['West', ''], ['West', null],
    ]
    const layout = buildPivotLayout(grid, { rowFields: ['Region'], values: [{ field: 'Amount', agg }] })
    expect(layout.matrix.at(-1)?.[1]).toBe(expected)
  })

  it('coerces text numbers for calculated pivot fields too', () => {
    const layout = buildPivotLayout(
      [['Region', 'Amount'], ['East', '100'], ['West', '50']],
      { rowFields: ['Region'], values: [{ field: 'Twice', agg: 'sum', formula: '=Amount*2' }] },
    )
    expect(layout.matrix.at(-1)?.[1]).toBe(300)
  })

  it('orders finite and non-finite sort keys deterministically and keeps blanks last', () => {
    const rows = [[3], [NaN], [1], [Infinity], [2], [-Infinity], [null]]
    expect(computeSortedRowOrder(rows, 0, true)).toEqual([2, 4, 0, 1, 3, 5, 6])
    expect(computeSortedRowOrder(rows, 0, false)).toEqual([1, 3, 5, 0, 4, 2, 6])
  })
})
