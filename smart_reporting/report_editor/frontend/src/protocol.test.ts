import { describe, expect, it } from 'vitest'

import { findProtocolMarkers, protocolMarkersUnchanged, restoreProtocolMarkers } from './protocol'

describe('report protocol markers', () => {
  it('finds section, citation, and analysis markers without transforming markdown', () => {
    const markdown = [
      '[[section:summary]]',
      '## 经营摘要[[analysis:analysis_001]]',
      '收入同比增长。[[citation:revenue_001]]',
    ].join('\n')

    expect(findProtocolMarkers(markdown)).toEqual([
      expect.objectContaining({ kind: 'section', raw: '[[section:summary]]' }),
      expect.objectContaining({ kind: 'analysis', raw: '[[analysis:analysis_001]]' }),
      expect.objectContaining({ kind: 'citation', raw: '[[citation:revenue_001]]' }),
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

describe('Milkdown serialization of protocol markers', () => {
  it('restores the markers Milkdown escapes before they are saved', async () => {
    const { Editor, defaultValueCtx, rootCtx } = await import('@milkdown/kit/core')
    const { commonmark } = await import('@milkdown/kit/preset/commonmark')
    const { getMarkdown } = await import('@milkdown/kit/utils')
    const root = document.createElement('div')
    document.body.append(root)
    const source = '# 报告\n\n[[section:finance_1]]\n\n## 1. 概览\n\n正文[[citation:c_1]]。\n'
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
