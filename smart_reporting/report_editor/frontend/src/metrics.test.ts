import { describe, expect, it } from 'vitest'

import { documentMetrics } from './metrics'

describe('documentMetrics', () => {
  it('counts non-whitespace characters and paragraphs', () => {
    expect(documentMetrics('# 标题\n\n第一段\n\n第二段')).toBe('9 字 · 3 段 · 阅读 1 分钟')
  })
})
