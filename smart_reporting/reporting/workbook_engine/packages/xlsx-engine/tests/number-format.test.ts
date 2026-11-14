import { describe, expect, it } from 'vitest'

import { formatNumericValue } from '../src/number-format'

/// 45292 = 2024-01-01（Excel 序列数，自锚：25569=1970-01-01）
const NEW_YEAR = 45292
/// 45292.5 = 2024-01-01 12:00
const NOON = 45292.5

describe('formatNumericValue（导出显示格式化）', () => {
  it('prints quoted percent points without multiplying raw values', () => {
    expect(formatNumericValue(12.5, '0.000"%";-0.000"%"')).toBe('12.500%')
    expect(formatNumericValue(-12.5, '0.0"%";(0.0"%")')).toBe('(12.5%)')
    expect(formatNumericValue(-12.5, '0"%";[Red]-0"%"')).toBe('-13%')
    expect(formatNumericValue(0, '0"%";-0"%"')).toBe('0%')
  })
  it('renders builtin short date and datetime ids', () => {
    expect(formatNumericValue(NEW_YEAR, '14')).toBe('1/1/2024')
    expect(formatNumericValue(NOON, '22')).toBe('1/1/2024 12:00')
    expect(formatNumericValue(NOON, '20')).toBe('12:00')
  })

  it('renders explicit yyyy/m/d patterns with quoted CJK literals', () => {
    expect(formatNumericValue(NEW_YEAR, 'yyyy/m/d')).toBe('2024/1/1')
    expect(formatNumericValue(NEW_YEAR, 'yyyy-mm-dd')).toBe('2024-01-01')
    expect(formatNumericValue(NEW_YEAR, 'yyyy"年"m"月"d"日"')).toBe('2024年1月1日')
    expect(formatNumericValue(NOON, 'yyyy/m/d h:mm')).toBe('2024/1/1 12:00')
  })

  it('treats m after h as minutes and lone m as month', () => {
    // h:mm → minutes; m/d/yyyy → month (the regression the tokenizer exists for)
    expect(formatNumericValue(0.5, 'h:mm')).toBe('12:00') // serial 0.5 = 12:00
    expect(formatNumericValue(NEW_YEAR, 'm/d/yyyy')).toBe('1/1/2024')
    expect(formatNumericValue(NOON, 'm/d/yyyy h:mm')).toBe('1/1/2024 12:00')
    expect(formatNumericValue(0.25, 'h:mm')).toBe('6:00') // 0.25 天 = 06:00
    expect(formatNumericValue(1 / 240, 'mm:ss')).toBe('06:00') // 6 分钟 0 秒
  })

  it('renders 12-hour clock with AM/PM', () => {
    expect(formatNumericValue(NEW_YEAR + 1 / 24, 'h:mm AM/PM')).toBe('1:00 AM')
    expect(formatNumericValue(NOON + 1 / 24, 'h:mm AM/PM')).toBe('1:00 PM')
  })

  it('renders grouping, decimals, and percent; falls back honestly', () => {
    expect(formatNumericValue(1234567.891, '#,##0')).toBe('1,234,568')
    expect(formatNumericValue(1234567.891, '#,##0.00')).toBe('1,234,567.89')
    expect(formatNumericValue(0.4567, '0%')).toBe('46%')
    expect(formatNumericValue(0.4567, '0.00%')).toBe('45.67%')
    expect(formatNumericValue(3.14159, '0.00')).toBe('3.14')
    // unsupported patterns → raw value, never a wrong format
    expect(formatNumericValue(NEW_YEAR, '# ?/?')).toBe(String(NEW_YEAR))
    expect(formatNumericValue(NEW_YEAR, undefined)).toBe(String(NEW_YEAR))
  })

  it('refuses the 1900 leap-bug serial range instead of guessing', () => {
    expect(formatNumericValue(30, '14')).toBe('30')
  })
})
