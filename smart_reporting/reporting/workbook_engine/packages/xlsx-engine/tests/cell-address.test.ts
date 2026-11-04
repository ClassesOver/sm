import { describe, expect, it } from 'vitest'

import {
  columnIndex,
  columnLabel,
  formatAddress,
  parseAddress,
  parseRange,
  rangeAddresses,
} from '../src/cell-address'

describe('parseAddress', () => {
  it('parses plain A1', () => {
    expect(parseAddress('A1')).toEqual({ row: 0, column: 0 })
    expect(parseAddress('B2')).toEqual({ row: 1, column: 1 })
    expect(parseAddress('AA10')).toEqual({ row: 9, column: 26 })
    expect(parseAddress('XFD1048576')).toEqual({ row: 1048575, column: 16383 })
  })

  it('accepts $ anchors and trims whitespace', () => {
    expect(parseAddress('$C$33')).toEqual({ row: 32, column: 2 })
    expect(parseAddress(' A1 ')).toEqual({ row: 0, column: 0 })
  })

  it('rejects lowercase and malformed addresses', () => {
    expect(() => parseAddress('a1')).toThrow()
    expect(() => parseAddress('A0')).toThrow()
    expect(() => parseAddress('A')).toThrow()
    expect(() => parseAddress('1A')).toThrow()
    expect(() => parseAddress('')).toThrow()
  })
})

describe('columnLabel / columnIndex / formatAddress', () => {
  it('round-trips columns', () => {
    for (const column of [0, 1, 25, 26, 27, 701, 702, 16383]) {
      expect(columnIndex(columnLabel(column))).toBe(column)
    }
    expect(columnLabel(0)).toBe('A')
    expect(columnLabel(25)).toBe('Z')
    expect(columnLabel(26)).toBe('AA')
    expect(columnLabel(702)).toBe('AAA')
  })

  it('formats addresses', () => {
    expect(formatAddress(0, 0)).toBe('A1')
    expect(formatAddress(9, 26)).toBe('AA10')
    expect(() => formatAddress(-1, 0)).toThrow()
    expect(() => formatAddress(0, -1)).toThrow()
  })
})

describe('parseRange', () => {
  it('parses and normalizes', () => {
    expect(parseRange('A1:C10')).toEqual({ startRow: 0, startColumn: 0, endRow: 9, endColumn: 2 })
    expect(parseRange('B2')).toEqual({ startRow: 1, startColumn: 1, endRow: 1, endColumn: 1 })
    expect(parseRange(' C10 : A1 ')).toEqual({ startRow: 0, startColumn: 0, endRow: 9, endColumn: 2 })
    expect(() => parseRange('A1:B2:C3')).toThrow()
    expect(() => parseRange('A1:')).toThrow()
  })

  it('expands addresses row-major', () => {
    expect(rangeAddresses(parseRange('A1:B2'))).toEqual(['A1', 'B1', 'A2', 'B2'])
  })
})
