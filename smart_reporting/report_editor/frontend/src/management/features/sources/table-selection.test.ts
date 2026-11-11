import { expect, it } from 'vitest'
import { selectPage, tableChanges } from './table-selection'
const a = { database: 'warehouse', name: 'orders' }
const b = { database: 'warehouse', name: 'private_orders' }
const c = { database: 'warehouse', name: 'view_orders' }
it('选择和取消本页不改变其他页面的选择', () => {
  expect(selectPage([a], [b, c], true)).toEqual([a, b, c])
  expect(selectPage([a, b, c], [b], false)).toEqual([a, c])
  expect(selectPage([a, b], [b], true)).toEqual([a, b])
})
it('按数据库与表名比较范围，保留本地删除和新增', () => {
  expect(tableChanges([a, b], [b, c])).toEqual({ added: [c], removed: [a] })
  expect(tableChanges([a], [{ ...a, database: 'other' }])).toEqual({
    added: [{ ...a, database: 'other' }],
    removed: [a],
  })
})
