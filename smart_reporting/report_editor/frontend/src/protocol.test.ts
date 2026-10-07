import { describe, expect, it } from 'vitest'

import { findProtocolMarkers, protocolMarkersUnchanged, restoreProtocolMarkers } from './protocol'

describe('report protocol markers', () => {
  it('finds section, citation, analysis, claim and table markers without transforming markdown', () => {
    const markdown = [
      '[[section:summary]]',
      '## 经营摘要[[analysis:analysis_001]]',
      '收入同比增长。[[citation:revenue_001]]',
      '收入 3600 万元。[[claim:claim_001]]',
      '[[table:tbl_001]]',
      '| 指标 | 值 |',
      '| --- | ---: |',
      '| 收入 | 3600 |',
      '[[/table:tbl_001]]',
    ].join('\n')

    expect(findProtocolMarkers(markdown)).toEqual([
      expect.objectContaining({ kind: 'section', raw: '[[section:summary]]' }),
      expect.objectContaining({ kind: 'analysis', raw: '[[analysis:analysis_001]]' }),
      expect.objectContaining({ kind: 'citation', raw: '[[citation:revenue_001]]' }),
      expect.objectContaining({ kind: 'claim', raw: '[[claim:claim_001]]' }),
      expect.objectContaining({ kind: 'table', raw: '[[table:tbl_001]]' }),
      expect.objectContaining({ kind: 'table-close', raw: '[[/table:tbl_001]]' }),
    ])
    expect(protocolMarkersUnchanged(markdown, markdown)).toBe(true)
  })

  it('rejects deletion, editing, or reordering of protected markers', () => {
    const original = '[[section:a]]\n## 标题[[analysis:an_1]]\n正文 [[citation:x]]'

    expect(protocolMarkersUnchanged(original, '正文 [[citation:x]]')).toBe(false)
    expect(
      protocolMarkersUnchanged(original, '## 标题[[analysis:an_2]]\n正文 [[citation:x]]'),
    ).toBe(false)
    expect(
      protocolMarkersUnchanged(original, '[[citation:x]]\n正文 [[section:a]]'),
    ).toBe(false)

    const withTable = '[[table:t1]]\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n[[/table:t1]]'
    expect(protocolMarkersUnchanged(withTable, '| a | b |\n| --- | --- |\n| 1 | 2 |')).toBe(false)
    expect(protocolMarkersUnchanged(withTable, withTable.replace('[[table:t1]]', ''))).toBe(false)
    expect(protocolMarkersUnchanged(withTable, withTable.replace('[[/table:t1]]', ''))).toBe(false)
  })

  it('restores serializer-escaped protocol markers', () => {
    const serialized = [
      '\\[\\[section:section\\_001]]',
      '## 成本分析\\[\\[analysis:analysis\\_001]]',
      '正文\\[\\[citation:citation\\_001]]',
      '\\[\\[claim:claim\\_001]]',
      '\\[\\[table:tbl\\_001]]',
      '\\[\\[/table:tbl\\_001]]',
      '\\[\\[/claim:claim\\_001]]',
      '普通转义 \\[\\[not a marker]] 保持原样',
    ].join('\n')

    expect(restoreProtocolMarkers(serialized)).toBe(
      [
        '[[section:section_001]]',
        '## 成本分析[[analysis:analysis_001]]',
        '正文[[citation:citation_001]]',
        '[[claim:claim_001]]',
        '[[table:tbl_001]]',
        '[[/table:tbl_001]]',
        '\\[\\[/claim:claim\\_001]]',
        '普通转义 \\[\\[not a marker]] 保持原样',
      ].join('\n'),
    )
  })
})

describe('Milkdown serialization of protocol markers', () => {
  it('restores the markers Milkdown escapes before they are saved', async () => {
    const { Editor, defaultValueCtx, rootCtx } = await import('@milkdown/kit/core')
    const { commonmark } = await import('@milkdown/kit/preset/commonmark')
    const { getMarkdown } = await import('@milkdown/kit/utils')
    const root = document.createElement('div')
    document.body.append(root)
    const source = '# 报告\n\n[[section:finance_1]]\n\n## 1. 概览\n\n正文[[citation:c_1]]。\n\n[[table:tbl_1]]\n\n表格内容\n\n[[/table:tbl_1]]\n'
    const editor = await Editor.make()
      .config((ctx) => {
        ctx.set(rootCtx, root)
        ctx.set(defaultValueCtx, source)
      })
      .use(commonmark)
      .create()

    const serialized = editor.action(getMarkdown())

    expect(serialized).toContain('\\[\\[section:finance\\_1]]')
    expect(restoreProtocolMarkers(serialized)).toBe(source)
    await editor.destroy()
    root.remove()
  })
})

describe('正文来源组合', () => {
  it('合并相邻分析与引用，保留原始标记及其范围', async () => {
    const { groupProtocolMarkers } = await import('./protocol')
    const text = '正文[[analysis:analysis_001]] [[citation:revenue_001]][[analysis:analysis_002]]'
    const groups = groupProtocolMarkers(text)
    expect(groups).toHaveLength(1)
    expect(groups[0].map(marker => marker.value)).toEqual(['analysis_001', 'revenue_001', 'analysis_002'])
    expect(text.slice(groups[0][0].start, groups[0].at(-1)!.end)).toBe(text.slice(2))
  })
  it('正文和结构标记阻断组合', async () => {
    const { groupProtocolMarkers } = await import('./protocol')
    expect(groupProtocolMarkers('[[analysis:analysis_001]]正文[[analysis:analysis_002]]')).toHaveLength(2)
    expect(groupProtocolMarkers('[[citation:a]][[section:s]][[citation:b]]')).toHaveLength(3)
  })
})
