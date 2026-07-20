import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCopyFeedback } from './useCopyFeedback'

beforeEach(() => vi.useFakeTimers())

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('复制反馈状态', () => {
  it('复制成功后显示反馈，并在连续复制时重新计时', async () => {
    const copyAction = vi.fn(async () => undefined)
    const { result } = renderHook(() => useCopyFeedback(copyAction))

    await act(async () => result.current.copy())
    expect(result.current.copied).toBe(true)
    act(() => vi.advanceTimersByTime(1000))

    await act(async () => result.current.copy())
    act(() => vi.advanceTimersByTime(500))
    expect(result.current.copied).toBe(true)
    act(() => vi.advanceTimersByTime(900))
    expect(result.current.copied).toBe(false)
    expect(copyAction).toHaveBeenCalledTimes(2)
  })

  it('组件卸载时清理反馈定时器', async () => {
    const { result, unmount } = renderHook(() => useCopyFeedback(async () => undefined))

    await act(async () => result.current.copy())
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
