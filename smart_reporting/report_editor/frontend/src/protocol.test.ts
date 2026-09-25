import { describe, expect, it } from 'vitest'

import { findProtocolMarkers, protocolMarkersUnchanged, restoreProtocolMarkers } from './protocol'

describe('report protocol markers', () => {
  it('finds section and citation markers without transforming markdown', () => {
    const markdown = [
      '[[section:summary]]',
      '## 经营摘要',
      '收入同比增长。[[citation:revenue_001]]',
    ].join('\n')

    expect(findProtocolMarkers(markdown)).toEqual([
      expect.objectContaining({ kind: 'section', raw: '[[section:summary]]' }),
      expect.objectContaining({ kind: 'citation', raw: '[[citation:revenue_001]]' }),
    ])
    expect(protocolMarkersUnchanged(markdown, markdown)).toBe(true)
  })

  it('rejects deletion, editing, or reordering of protected markers', () => {
    const original = '[[section:a]]\n正文 [[citation:x]]'

    expect(protocolMarkersUnchanged(original, '正文 [[citation:x]]')).toBe(false)
    expect(
      protocolMarkersUnchanged(original, '[[section:a]]\n正文 [[citation:y]]'),
    ).toBe(false)
    expect(
      protocolMarkersUnchanged(original, '[[citation:x]]\n正文 [[section:a]]'),
    ).toBe(false)
  })

  it('restores serializer-escaped protocol markers', () => {
    const serialized = [
      '\\[\\[section:section\\_001]]',
      '## 成本分析\\[\\[analysis:analysis\\_001]]',
      '正文\\[\\[citation:citation\\_001]]',
      '普通转义 \\[\\[not a marker]] 保持原样',
    ].join('\n')

    expect(restoreProtocolMarkers(serialized)).toBe(
      [
        '[[section:section_001]]',
        '## 成本分析[[analysis:analysis_001]]',
        '正文[[citation:citation_001]]',
        '普通转义 \\[\\[not a marker]] 保持原样',
      ].join('\n'),
    )
  })
})
