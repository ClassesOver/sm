import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { AttachmentRef } from '../types'
import { useChatSidePanel } from './useChatSidePanel'

afterEach(cleanup)

describe('聊天侧栏状态', () => {
  it('保持文件与工作区互斥，并在线程切换时关闭', () => {
    const { result, rerender } = renderHook(
      ({ threadId }) => useChatSidePanel(threadId),
      { initialProps: { threadId: 'thread-1' } }
    )
    const attachment: AttachmentRef = {
      id: 'file-1',
      name: '合同.pdf',
      mimeType: 'application/pdf',
      size: 1024,
      modality: 'document'
    }

    act(() => result.current.openFile(attachment))
    expect(result.current.panel).toEqual({ type: 'file', attachment })
    act(() => result.current.openWorkspace())
    expect(result.current.panel).toEqual({ type: 'workspace' })
    act(() => result.current.closePanel())
    expect(result.current.panel).toEqual({ type: 'closed' })

    act(() => result.current.openWorkspace())
    rerender({ threadId: 'thread-2' })
    expect(result.current.panel).toEqual({ type: 'closed' })
  })
})
