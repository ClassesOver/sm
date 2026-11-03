import { describe, expect, it } from 'vitest'

import {
  applyFlashFillTemplate,
  computeSortChanges,
  computeSortedRowOrder,
  inferFlashFillTemplate,
} from '../src'

function cellsOf(rows: Array<Record<string, string | number | boolean | null>>): (address: string) => {
  value: string | number | boolean | null
  formula?: string | undefined
} {
  return (address) => {
    const column = address.match(/^[A-Z]+/)?.[0] ?? ''
    const row = Number(address.match(/\d+$/)?.[0] ?? 0)
    const value = rows[row - 1]?.[column] ?? null
    return { value }
  }
}

describe('range sorting', () => {
  it('orders rows stably with blanks last in both directions', () => {
    // 3 < 1 < 2 numerically; blank row sorts last ascending, first descending
    const rows = [
      [3, 'a'],
      [null, 'b'],
      [1, 'c'],
      [2, 'd'],
    ]
    expect(computeSortedRowOrder(rows, 0, true)).toEqual([2, 3, 0, 1])
    // descending: blanks still last (Excel behavior)
    expect(computeSortedRowOrder(rows, 0, false)).toEqual([0, 3, 2, 1])
    // ties keep input order (stable)
    const tied = [
      ['x', 1],
      ['x', 2],
    ]
    expect(computeSortedRowOrder(tied, 0, true)).toEqual([0, 1])
  })

  it('computes per-cell rewrites for a sorted range', () => {
    // A1:B4, header + 3 data rows; sort by B ascending
    const rows: Array<Record<string, string | number | null>> = [
      { A: 'name', B: 'qty' },
      { A: 'c', B: 3 },
      { A: 'a', B: 1 },
      { A: 'b', B: 2 },
    ]
    const changes = computeSortChanges(
      { range: 'A1:B4', byColumn: 'B', ascending: true, hasHeader: true },
      cellsOf(rows),
    )
    // target order: a(1), b(2), c(3) — column A moves rows, B stays sorted
    const map = new Map(changes.map((change) => [change.address, change.after]))
    expect(map.get('A2')).toBe('a')
    expect(map.get('A3')).toBe('b')
    expect(map.get('A4')).toBe('c')
    expect(map.get('B2')).toBe(1)
    expect(map.get('B4')).toBe(3)
  })

  it('rejects formulas in the range and out-of-range key columns', () => {
    const withFormula = (address: string) =>
      address === 'B2' ? { value: 5, formula: '=A2' } : { value: 1 }
    expect(() =>
      computeSortChanges({ range: 'A1:B3', byColumn: 'B', ascending: true, hasHeader: false }, withFormula),
    ).toThrow(/formula at B2/)
    expect(() =>
      computeSortChanges(
        { range: 'A1:B3', byColumn: 'C', ascending: true, hasHeader: false },
        cellsOf([]),
      ),
    ).toThrow(/outside the range/)
    // a header-only range cannot sort
    expect(() =>
      computeSortChanges({ range: 'A1:A2', byColumn: 'A', ascending: true, hasHeader: true }, cellsOf([])),
    ).toThrow(/at least two data rows/)
  })
})

describe('flash fill', () => {
  it('infers a concatenation template from examples', () => {
    const template = inferFlashFillTemplate([
      { source: ['Ada', 'Lovelace'], output: 'Ada.Lovelace@example.com' },
      { source: ['Grace', 'Hopper'], output: 'Grace.Hopper@example.com' },
    ])
    expect(template).toEqual([
      { kind: 'field', index: 0 },
      { kind: 'literal', text: '.' },
      { kind: 'field', index: 1 },
      { kind: 'literal', text: '@example.com' },
    ])
    expect(applyFlashFillTemplate(template!, ['Alan', 'Turing'])).toBe('Alan.Turing@example.com')
  })

  it('prefers the longest source field and rejects unexplainable examples', () => {
    // 'Beijing' and 'Bei' both match — the longest wins
    const template = inferFlashFillTemplate([
      { source: ['Beijing', 'CN'], output: 'Beijing-CN' },
      { source: ['Paris', 'FR'], output: 'Paris-FR' },
    ])
    expect(template).toEqual([
      { kind: 'field', index: 0 },
      { kind: 'literal', text: '-' },
      { kind: 'field', index: 1 },
    ])
    // a transformed example ('LOVELACE' upper-casing) cannot be explained
    expect(
      inferFlashFillTemplate([
        { source: ['Ada', 'Lovelace'], output: 'ADA LOVELACE' },
        { source: ['Grace', 'Hopper'], output: 'GRACE HOPPER' },
      ]),
    ).toBeNull()
    // no field reference at all
    expect(inferFlashFillTemplate([{ source: ['ab', 'cd'], output: 'xyz' }])).toBeNull()
  })
})
