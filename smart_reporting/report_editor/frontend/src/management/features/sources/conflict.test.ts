import { describe, it, expect } from 'vitest'
import { mergeDraft } from './conflict'
describe('三方合并', () => {
  it('保留单边修改，双改要求选择，不包含连接秘密', () => {
    const result = mergeDraft(
      { name: '旧名称', database: 'db' },
      { name: '本地名称', database: 'db' },
      { name: '远端名称', database: 'db2' },
    )
    expect(result.values).toEqual({ name: '本地名称', database: 'db2' })
    expect(result.conflicts).toEqual(['name'])
  })
  it('两端改成同值没有冲突', () => {
    expect(
      mergeDraft({ name: 'a' }, { name: 'b' }, { name: 'b' }).conflicts,
    ).toEqual([])
  })
})
