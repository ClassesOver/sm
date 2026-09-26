import { describe, expect, it, vi } from 'vitest'

import { configureSelectionAISuggestions, selectionAIProvider } from './ai'

describe('selectionAIProvider', () => {
  it.each([
    ['', 'polish'],
    ['正文', 'unknown'],
    ['正文 [[citation:x]]', 'polish'],
    ['[[section:summary]] 正文', 'shorten'],
    // Crepe 序列化后的选区形态：协议标记已被转义。
    ['正文\\[\\[citation:revenue\\_001]]', 'polish'],
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

    expect(chunks).toEqual(['改写后的', '正文'])
    expect(streamRewrite).toHaveBeenCalledWith(
      '原始正文',
      'professional',
      controller.signal,
    )
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
