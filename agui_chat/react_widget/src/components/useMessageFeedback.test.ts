import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChatMessage } from '../types'
import { useMessageFeedback } from './useMessageFeedback'

afterEach(cleanup)

const message: ChatMessage = { id: 'assistant-1', role: 'assistant', content: '回答' }

describe('消息反馈状态', () => {
  it('切换同一反馈并保持不同消息互相独立', () => {
    const onFeedback = vi.fn()
    const second = { ...message, id: 'assistant-2' }
    const { result } = renderHook(() => useMessageFeedback(onFeedback))

    act(() => result.current.toggleFeedback(message, 'positive'))
    expect(result.current.feedback).toEqual({ 'assistant-1': 'positive' })
    act(() => result.current.toggleFeedback(message, 'positive'))
    expect(result.current.feedback['assistant-1']).toBeNull()
    act(() => result.current.toggleFeedback(second, 'negative'))
    expect(result.current.feedback).toEqual({
      'assistant-1': null,
      'assistant-2': 'negative'
    })
    expect(onFeedback).toHaveBeenLastCalledWith(second, 'negative')
  })

  it('始终调用最新的反馈回调', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { result, rerender } = renderHook(
      ({ onFeedback }) => useMessageFeedback(onFeedback),
      { initialProps: { onFeedback: first } }
    )

    rerender({ onFeedback: second })
    act(() => result.current.toggleFeedback(message, 'positive'))
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith(message, 'positive')
  })
})
