import { describe, expect, it } from 'vitest'

import { headingStructureStatus } from './structure'

describe('headingStructureStatus', () => {
  it('reports heading level jumps as a soft warning', () => {
    expect(
      headingStructureStatus([
        { id: 'a', level: 1, text: '摘要' },
        { id: 'b', level: 3, text: '明细' },
      ]),
    ).toEqual({ label: '标题层级跳跃 1 处', warning: true })
  })

  it('reports a valid hierarchy', () => {
    expect(
      headingStructureStatus([
        { id: 'a', level: 1, text: '摘要' },
        { id: 'b', level: 2, text: '明细' },
      ]),
    ).toEqual({ label: '结构正常', warning: false })
  })
})
