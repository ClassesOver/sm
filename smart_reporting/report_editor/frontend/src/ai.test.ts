import { describe, expect, it, vi } from 'vitest'

import { configureSelectionAISuggestions, resolveSelectionAIAction, selectionAIProvider } from './ai'

describe('selectionAIProvider', () => {
  it('keeps references locally and releases only a complete candidate', async () => {
    const streamRewrite = vi.fn(async function* (selection: string) { yield selection.replace('原文', '润色后') })
    const provider = selectionAIProvider({ streamRewrite })
    const chunks = await Array.fromAsync(provider({ document: '', selection: '原文[[citation:revenue_001]]原文[[claim:claim_001]]', instruction: 'polish' }, new AbortController().signal))
    expect(chunks).toEqual(['润色后[[citation:revenue_001]]润色后[[claim:claim_001]]'])
    expect(streamRewrite.mock.calls.map(call => call[0])).toEqual(['原文', '原文'])
  })

  it('keeps punctuation-only pieces between references instead of sending them to the model', async () => {
    // 引用通常紧贴句号：“……增长5%[[citation]]。”；单独的“。”不是可改写正文。
    const streamRewrite = vi.fn(async function* (selection: string) { yield selection.replace('收入增长', '收入稳步增长') })
    const provider = selectionAIProvider({ streamRewrite })
    const chunks = await Array.fromAsync(provider({ document: '', selection: '收入增长[[citation:revenue_001]]。', instruction: 'polish' }, new AbortController().signal))
    expect(chunks).toEqual(['收入稳步增长[[citation:revenue_001]]。'])
    expect(streamRewrite.mock.calls.map(call => call[0])).toEqual(['收入增长'])
  })

  it('does not release partial content when a later segment fails', async () => {
    const streamRewrite = vi.fn(async function* (selection: string) {
      if (selection === '失败') throw new Error('network')
      yield '已改写'
    })
    const chunks: string[] = []
    await expect((async () => {
      for await (const chunk of selectionAIProvider({ streamRewrite })({ document: '', selection: '原文[[citation:revenue_001]]失败', instruction: 'polish' }, new AbortController().signal)) chunks.push(chunk)
    })()).rejects.toThrow('network')
    expect(chunks).toEqual([])
  })

  it('rejects invented source markers returned by the model', async () => {
    const provider = selectionAIProvider({ streamRewrite: async function* () { yield '改写[[citation:fake]]' } })
    await expect(Array.fromAsync(provider({ document: '', selection: '原文', instruction: 'polish' }, new AbortController().signal))).rejects.toThrow('无效引用')
  })
  it.each([
    ['', 'polish'],
    ['正文', 'unknown'],
    ['[[section:summary]] 正文', 'shorten'],
    // Crepe 序列化后的选区形态：协议标记已被转义。
    ['\\[\\[section:summary]]\n\n正文', 'expand'],
  ])('rejects invalid selection or action before the API call', async (selection, instruction) => {
    const streamRewrite = vi.fn()
    const provider = selectionAIProvider({ streamRewrite })

    await expect(
      Array.fromAsync(
        provider(
          { document: '# 报告', selection, instruction },
          new AbortController().signal,
        ),
      ),
    ).rejects.toThrow()
    expect(streamRewrite).not.toHaveBeenCalled()
  })

  it('forwards a fixed action and yields markdown chunks', async () => {
    const streamRewrite = vi.fn(async function* () {
      yield '改写后的'
      yield '正文'
    })
    const provider = selectionAIProvider({ streamRewrite })
    const controller = new AbortController()

    const chunks = await Array.fromAsync(
      provider(
        { document: '# 报告', selection: '原始正文', instruction: 'professional' },
        controller.signal,
      ),
    )

    expect(chunks).toEqual(['改写后的正文'])
    expect(streamRewrite).toHaveBeenCalledWith(
      '原始正文',
      'professional',
      controller.signal,
    )
  })

  it('maps typed keywords that pick exactly one preset to that preset action', async () => {
    // 指令框有输入时默认选中“自定义要求”行：输入“润色”后直接回车提交的是原文。
    expect(resolveSelectionAIAction('润色')).toBe('polish')
    expect(resolveSelectionAIAction(' 专业报告语气 ')).toBe('professional')
    expect(resolveSelectionAIAction('精简')).toBe('shorten')
    expect(resolveSelectionAIAction('把它写长一点')).toBeNull()
    const streamRewrite = vi.fn(async function* () { yield '改写' })
    const provider = selectionAIProvider({ streamRewrite })
    const signal = new AbortController().signal
    await Array.fromAsync(provider({ document: '# 报告', selection: '原始正文', instruction: '润色' }, signal))
    expect(streamRewrite).toHaveBeenCalledWith('原始正文', 'polish', signal)
  })

  it('exposes only the four report rewrite actions', () => {
    const actions: string[] = ['default-action']
    const builder = {
      clear: vi.fn(() => {
        actions.length = 0
        return builder
      }),
      addItem: vi.fn((id: string) => {
        actions.push(id)
        return builder
      }),
    }

    configureSelectionAISuggestions(builder as never)

    expect(builder.clear).toHaveBeenCalledOnce()
    expect(actions).toEqual(['polish', 'shorten', 'expand', 'professional'])
  })
})
