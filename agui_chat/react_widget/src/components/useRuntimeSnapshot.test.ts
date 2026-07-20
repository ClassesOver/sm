import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import type { RuntimeSnapshot } from '../types'
import { useRuntimeSnapshot } from './useRuntimeSnapshot'

afterEach(cleanup)

function snapshot(threadId: string, error = ''): RuntimeSnapshot {
  return {
    messages: [],
    sessions: [],
    session: null,
    hostState: {} as RuntimeSnapshot['hostState'],
    agentState: {},
    threadId,
    running: false,
    transportState: null,
    loadingSessions: false,
    error
  }
}

function runtimeWith(initial: RuntimeSnapshot) {
  let current = initial
  let listener: (() => void) | undefined
  const unsubscribe = vi.fn()
  const runtime = {
    getSnapshot: vi.fn(() => current),
    subscribe: vi.fn((nextListener: () => void) => {
      listener = nextListener
      return unsubscribe
    })
  } as unknown as ChatRuntime
  return {
    runtime,
    unsubscribe,
    emit(next: RuntimeSnapshot) {
      current = next
      listener?.()
    }
  }
}

describe('运行时快照订阅', () => {
  it('切换运行时时立即同步快照并清理旧订阅', async () => {
    const first = runtimeWith(snapshot('thread-1'))
    const second = runtimeWith(snapshot('thread-2'))
    const { result, rerender, unmount } = renderHook(
      ({ runtime }) => useRuntimeSnapshot(runtime),
      { initialProps: { runtime: first.runtime } }
    )

    expect(result.current.threadId).toBe('thread-1')
    rerender({ runtime: second.runtime })
    await waitFor(() => expect(result.current.threadId).toBe('thread-2'))
    expect(first.unsubscribe).toHaveBeenCalledOnce()

    act(() => second.emit(snapshot('thread-2', '连接失败')))
    expect(result.current.error).toBe('连接失败')
    unmount()
    expect(second.unsubscribe).toHaveBeenCalledOnce()
  })
})
