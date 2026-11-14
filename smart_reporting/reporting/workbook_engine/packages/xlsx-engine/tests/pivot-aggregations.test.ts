import { expect, it } from 'vitest'
import { buildPivotLayout, type PivotScalar } from '../src/pivot-layout'

const cases = [
  ['product', 48, 5, null, 240],
  ['countNums', 3, 1, 0, 4],
  ['stdDev', 2, null, null, Math.sqrt(35 / 12)],
  ['stdDevp', Math.sqrt(8 / 3), 0, null, Math.sqrt(35 / 16)],
  ['var', 4, null, null, 35 / 12],
  ['varp', 8 / 3, 0, null, 35 / 16],
] as const
const grid: PivotScalar[][] = [['Region', 'Amount'], ['East', 2], ['East', 4], ['East', '6'], ['East', null], ['East', ''], ['East', false], ['East', 'text'], ['One', 5], ['Empty', null], ['Empty', ''], ['Empty', false], ['Empty', 'text']]

it.each(cases)('bakes %s with source numeric coercion and correct bucket/grand-total sample sizes', (agg, east, one, empty, total) => {
  const layout = buildPivotLayout(grid, { rowFields: ['Region'], values: [{ field: 'Amount', agg }] })
  const value = (label: string) => layout.matrix.find(row => row[0] === label)![1]
  expect(value('East')).toBeCloseTo(east)
  if (one === null) expect(value('One')).toBeNull()
  else expect(value('One')).toBeCloseTo(one)
  if (empty === null) expect(value('Empty')).toBeNull()
  else expect(value('Empty')).toBe(empty)
  expect(value('Grand Total')).toBeCloseTo(total)
})

it.each([
  ['product', 0], ['countNums', 3], ['var', 28 / 3], ['varp', 56 / 9],
  ['stdDev', Math.sqrt(28 / 3)], ['stdDevp', Math.sqrt(56 / 9)],
] as const)('includes zero and negatives for %s instead of discarding them', (agg, expected) => {
  const layout = buildPivotLayout([['Region', 'Amount'], ['East', -2], ['East', 0], ['East', 4]], { rowFields: 'Region', values: [{ field: 'Amount', agg }] })
  expect(layout.matrix[1]![1]).toBeCloseTo(expected)
})

it('applies report filters and value filters to the new aggregation before calculating totals', () => {
  const layout = buildPivotLayout([['Region', 'Period', 'Amount'], ['East', 'Now', 2], ['East', 'Now', 4], ['West', 'Now', 3], ['West', 'Before', 100]], {
    rowFields: 'Region', pageFilters: [{ field: 'Period', selected: ['Now'] }], values: [{ field: 'Amount', agg: 'product' }],
    filters: [{ kind: 'value', field: 'Region', valueIndex: 0, op: 'greaterThan', from: 5 }],
  })
  expect(layout.matrix).toEqual([['Region', 'Product of Amount'], ['East', 8], ['Grand Total', 8]])
})
