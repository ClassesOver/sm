import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ChatMessage } from '../types'
import { useChatAutoScroll } from './useChatAutoScroll'

afterEach(cleanup)

function ScrollHarness({
  threadId, messages, content
}: {
  threadId: string
  messages: ChatMessage[]
  content: string
}) {
  const scroll = useChatAutoScroll(threadId, messages)
  return <div data-testid="消息滚动区" ref={scroll.scrollRef} onScroll={scroll.handleScroll}>{content}</div>
}

describe('聊天自动滚动', () => {
  it('尊重用户滚动，并在新消息和线程切换时恢复跟随', async () => {
    const initial = [{ id: 'assistant-1', role: 'assistant' as const, content: '初始回复' }]
    const view = render(<ScrollHarness threadId="thread-1" messages={initial} content="初始回复" />)
    const scroller = screen.getByTestId('消息滚动区') as HTMLDivElement
    let scrollTop = 0
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, get: () => 1000 },
      clientHeight: { configurable: true, get: () => 400 },
      scrollTop: { configurable: true, get: () => scrollTop, set: (value) => { scrollTop = Number(value) } }
    })

    scrollTop = 500
    fireEvent.scroll(scroller)
    view.rerender(<ScrollHarness threadId="thread-1" messages={initial} content="流式更新" />)
    await act(async () => undefined)
    expect(scrollTop).toBe(500)

    const withUser = [...initial, { id: 'user-1', role: 'user' as const, content: '继续' }]
    view.rerender(<ScrollHarness threadId="thread-1" messages={withUser} content="新问题" />)
    expect(scrollTop).toBe(1000)

    scrollTop = 300
    fireEvent.scroll(scroller)
    view.rerender(<ScrollHarness threadId="thread-2" messages={initial} content="新线程" />)
    expect(scrollTop).toBe(1000)

    scrollTop = 600
    view.rerender(<ScrollHarness threadId="thread-2" messages={initial} content="新线程流式更新" />)
    await act(async () => undefined)
    expect(scrollTop).toBe(1000)
  })
})
