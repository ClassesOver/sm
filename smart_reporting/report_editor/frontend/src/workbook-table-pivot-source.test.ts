import { expect, it } from 'vitest'
import { tablePivotColumnChangeReason } from './workbook-table-pivot-source'

const table = { name: 'Sales', columns: [{ displayName: 'Region' }, { displayName: 'Amount' }] }
const cache = '<pivotCacheDefinition xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cacheSource><worksheetSource name="sAlEs"/></cacheSource><cacheFields><cacheField name="Region"/><cacheField name="Amount"/></cacheFields></pivotCacheDefinition>'

it('rejects cached field loss after a pending table rename using the original identity', () => {
  expect(tablePivotColumnChangeReason({ ...table, name: 'CurrentSales' }, ['Region'], [cache], ['Sales'])).toContain('透视缓存仍引用')
  expect(tablePivotColumnChangeReason(table, ['Region', 'Revenue'], [cache])).toContain('透视缓存仍引用')
})

it('allows ordinary tables, fixed-range sources, row resizing and removing a new uncached column', () => {
  expect(tablePivotColumnChangeReason(table, ['Region'], [])).toBeUndefined()
  expect(tablePivotColumnChangeReason(table, ['Region'], [cache.replace('name="sAlEs"', 'ref="A1:B3"')])).toBeUndefined()
  expect(tablePivotColumnChangeReason(table, ['Region', 'Amount'], [cache])).toBeUndefined()
  expect(tablePivotColumnChangeReason({ ...table, columns: [...table.columns, { displayName: 'New' }] }, ['Region', 'Amount'], [cache])).toBeUndefined()
})

it('reports missing, unreadable or malformed source evidence only when columns could be lost', () => {
  expect(tablePivotColumnChangeReason(table, ['Region'], undefined)).toContain('正在同步')
  expect(tablePivotColumnChangeReason(table, ['Region'], new Error('来源不可读取'))).toBe('来源不可读取')
  expect(tablePivotColumnChangeReason(table, ['Region'], [cache + '<broken>'])).toBeTruthy()
  expect(tablePivotColumnChangeReason(table, ['Region', 'Amount'], undefined)).toBeUndefined()
})

it('does not assign an old source name to a different table that reuses it in the draft', () => {
  expect(tablePivotColumnChangeReason(table, ['Region'], [cache], ['Other'])).toBeUndefined()
  expect(tablePivotColumnChangeReason(table, ['Region'], [cache], [])).toBeUndefined()
})

it('preserves literal XML escape-looking field names from locally generated caches', () => {
  const literal = { name: 'Sales', columns: [{ displayName: '_x0041_' }] }
  expect(tablePivotColumnChangeReason(literal, ['Changed'], [cache.replace('name="Amount"', 'name="_x0041_"')])).toContain('透视缓存仍引用')
})

it('rejects swapping cached column names even when the set of names is unchanged', () => {
  expect(tablePivotColumnChangeReason(table, ['Amount', 'Region'], [cache])).toContain('透视缓存仍引用')
})

it('keeps source identities at their physical columns when resizing the left edge', () => {
  const shifted = { ...table, range: { startColumn: 2 } }
  expect(tablePivotColumnChangeReason(shifted, ['New', 'Region', 'Amount'], [cache], undefined, 1)).toBeUndefined()
  expect(tablePivotColumnChangeReason(shifted, ['Amount'], [cache], undefined, 3)).toContain('透视缓存仍引用')
})

it('allows prevalidated owned source renames and checks later draft names against calculated fields', () => {
  const support = { fieldNames: ['Region', 'Amount'], calculatedNames: ['Profit'] }
  expect(tablePivotColumnChangeReason(table, ['Area', 'Revenue'], [cache], undefined, undefined, support)).toBeUndefined()
  expect(tablePivotColumnChangeReason(table, ['Amount', 'Region'], [cache], undefined, undefined, support)).toBeUndefined()
  const pending = { ...table, columns: [{ displayName: 'Region' }, { displayName: 'Revenue' }] }
  expect(tablePivotColumnChangeReason(pending, ['Region', 'Profit'], [cache], undefined, undefined, support)).toContain('计算字段冲突')
  expect(tablePivotColumnChangeReason(table, ['Region'], [cache], undefined, undefined, support)).toContain('透视缓存仍引用')
  expect(tablePivotColumnChangeReason(table, ['Area', 'Revenue'], [cache], undefined, undefined, new Error('含原生控件'))).toContain('含原生控件')
})
