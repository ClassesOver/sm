import { describe, expect, it } from 'vitest'

import {
  groupLabel,
  groupValue,
  isValidGrouping,
  parseDateParts,
  type PivotFieldGrouping,
} from '../src/pivot-grouping'

const dateYear: PivotFieldGrouping = { kind: 'date', dateUnit: 'year' }
const dateQuarter: PivotFieldGrouping = { kind: 'date', dateUnit: 'quarter' }
const dateMonth: PivotFieldGrouping = { kind: 'date', dateUnit: 'month' }
const rangeStep10: PivotFieldGrouping = { kind: 'range', rangeStep: 10 }
const rangeStart50: PivotFieldGrouping = { kind: 'range', rangeStep: 25, rangeStart: 50 }

describe('pivot field grouping', () => {
  it('parses Excel serial dates and direct date strings', () => {
    // Excel 的 1900 日期系统中，序列 1 对应 1900-01-01。
    expect(parseDateParts(1)).toEqual({ year: 1900, month: 1 })
    // 2026-03-15 → serial 46096
    expect(parseDateParts(46096)).toEqual({ year: 2026, month: 3 })
    expect(parseDateParts('2026-03-15')).toEqual({ year: 2026, month: 3 })
    expect(parseDateParts(' 2026/3/5 ')).toEqual({ year: 2026, month: 3 })
    expect(parseDateParts('2026-13-01')).toBeNull()
    expect(parseDateParts('not a date')).toBeNull()
    expect(parseDateParts(-1)).toBeNull()
  })

  it('groups dates into year/quarter/month labels', () => {
    expect(groupValue(dateYear, '2026-03-15')).toEqual({ label: '2026', sort: 2026 })
    expect(groupValue(dateQuarter, '2026-03-15')).toEqual({ label: 'Q1', sort: 1 })
    expect(groupValue(dateQuarter, '1999-12-01')).toEqual({ label: 'Q4', sort: 4 })
    expect(groupValue(dateMonth, '2026-03-15')).toEqual({ label: 'Mar', sort: 3 })
    // serial-number input goes through the same path
    expect(groupLabel(dateYear, 46096)).toBe('2026')
  })

  it('groups numbers into half-open range buckets with stable labels', () => {
    expect(groupValue(rangeStep10, 13)).toEqual({ label: '10-20', sort: 10 })
    expect(groupValue(rangeStep10, 20)).toEqual({ label: '20-30', sort: 20 })
    expect(groupValue(rangeStep10, -3)).toEqual({ label: '-10-0', sort: -10 })
    expect(groupValue(rangeStart50, 60)).toEqual({ label: '50-75', sort: 50 })
    // float noise collapses into a clean boundary label
    expect(groupValue({ kind: 'range', rangeStep: 0.1 }, 0.5).label).toBe('0.5-0.6')
  })

  it('passes blanks through as empty labels and unparseable values verbatim', () => {
    expect(groupLabel(dateYear, null)).toBe('')
    expect(groupLabel(dateYear, '')).toBe('')
    expect(groupLabel(dateYear, undefined)).toBe('')
    expect(groupLabel(dateYear, 'soon')).toBe('soon')
    expect(groupLabel(rangeStep10, 'abc')).toBe('abc')
    expect(groupLabel(rangeStep10, '13')).toBe('10-20') // numeric strings bucket
  })

  it('validates grouping rules from extLst / IPC payloads', () => {
    expect(isValidGrouping({ kind: 'date', dateUnit: 'month' })).toBe(true)
    expect(isValidGrouping({ kind: 'date', dateUnit: 'week' })).toBe(false)
    expect(isValidGrouping({ kind: 'range', rangeStep: 5 })).toBe(true)
    expect(isValidGrouping({ kind: 'range', rangeStep: 0 })).toBe(false)
    expect(isValidGrouping({ kind: 'range', rangeStep: -1 })).toBe(false)
    expect(isValidGrouping({ kind: 'range', rangeStep: 5, rangeStart: 2.5 })).toBe(true)
    expect(isValidGrouping({ kind: 'range', rangeStep: '5' })).toBe(false)
    expect(isValidGrouping({ kind: 'nope' })).toBe(false)
    expect(isValidGrouping(null)).toBe(false)
  })
})
