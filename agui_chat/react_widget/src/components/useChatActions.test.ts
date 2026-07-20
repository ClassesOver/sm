import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import type { ChatMessage, OdooHostSnapshot } from '../types'
import { testHostState, v2Props } from '../test/fixtures'
import { useChatActions } from './useChatActions'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function runtimeMock() {
  return {
    send: vi.fn(async () => true),
    newSession: vi.fn(async () => undefined),
    refreshSessions: vi.fn(async () => true),
    loadSession: vi.fn(async () => undefined),
    archiveSession: vi.fn(async () => true),
    selectRelationCandidates: vi.fn(async () => '已选择客户'),
    selectRecordCandidate: vi.fn(async () => '已选择记录'),
    removeMenuMention: vi.fn(),
    removeMention: vi.fn(),
    regenerate: vi.fn(async () => undefined),
    confirmTool: vi.fn(async () => undefined),
    undoTool: vi.fn(async () => undefined),
    stop: vi.fn(),
    uploadAttachment: vi.fn(async () => ({
      id: 'file-1', name: '合同.pdf', mimeType: 'application/pdf', size: 1, modality: 'document' as const
    })),
    deleteAttachment: vi.fn(async () => undefined)
  }
}

describe('聊天动作适配', () => {
  it('发送成功后清空工作区引用并上报完整上下文', async () => {
    const runtime = runtimeMock()
    const onInteraction = vi.fn()
    const clearWorkspaceReferences = vi.fn()
    const selection = {
      menuId: 1, actionId: 11, name: '客户', path: ['销售', '客户'],
      fullPath: '销售 / 客户', valid: true
    }
    const { result } = renderHook(() => useChatActions({
      runtime: runtime as unknown as ChatRuntime,
      props: v2Props({ onInteraction }),
      messages: [],
      hostState: testHostState,
      clearWorkspaceReferences
    }))

    await act(async () => result.current.send('打开客户', [], selection, undefined, []))
    expect(runtime.send).toHaveBeenCalledWith('打开客户', [], selection, undefined, undefined, [])
    expect(clearWorkspaceReferences).toHaveBeenCalledOnce()
    expect(onInteraction).toHaveBeenCalledWith({
      type: 'send', content: '打开客户', attachments: [], menuMention: selection,
      mentions: undefined, skills: undefined, workspaceReferences: []
    })
  })

  it('发送失败时不清空引用或上报交互', async () => {
    const runtime = runtimeMock()
    runtime.send.mockResolvedValue(false)
    const onInteraction = vi.fn()
    const clearWorkspaceReferences = vi.fn()
    const { result } = renderHook(() => useChatActions({
      runtime: runtime as unknown as ChatRuntime,
      props: v2Props({ onInteraction }),
      messages: [],
      hostState: testHostState,
      clearWorkspaceReferences
    }))

    await act(async () => result.current.send('失败消息', [], undefined, undefined, []))
    expect(clearWorkspaceReferences).not.toHaveBeenCalled()
    expect(onInteraction).not.toHaveBeenCalled()
  })

  it('关系与记录选择使用最新宿主快照生成发送事件', async () => {
    const runtime = runtimeMock()
    const onInteraction = vi.fn()
    const tool = { id: 'tool-1', name: 'odoo.apply_filter' }
    const candidate = { token: 'record-1', displayName: '上海客户' }
    const { result, rerender } = renderHook(
      ({ hostState }: { hostState: OdooHostSnapshot }) => useChatActions({
        runtime: runtime as unknown as ChatRuntime,
        props: v2Props({ onInteraction }),
        messages: [],
        hostState,
        clearWorkspaceReferences: vi.fn()
      }),
      { initialProps: { hostState: testHostState } }
    )
    const actions = result.current
    rerender({ hostState: { ...testHostState, snapshotId: 'snapshot-2', hostRevision: 2 } })

    await act(async () => {
      actions.selectRelation(tool, [{ id: 7, displayName: '重点客户', selected: false }])
      actions.selectRecord(tool, candidate)
      await Promise.resolve()
    })
    expect(runtime.selectRelationCandidates).toHaveBeenCalledOnce()
    expect(onInteraction).toHaveBeenCalledWith({
      type: 'send', content: '已选择记录', attachments: [],
      recordSelection: { ...candidate, snapshotId: 'snapshot-2', hostRevision: 2 }
    })
    expect(result.current).toBe(actions)
  })

  it('统一反馈、重新生成、建议、停止和工具动作', () => {
    const runtime = runtimeMock()
    const onInteraction = vi.fn()
    const onFeedback = vi.fn()
    const message: ChatMessage = { id: 'assistant-1', role: 'assistant', content: '回答' }
    const tool = { id: 'tool-1', name: 'odoo.save_current_form' }
    const suggestion = { title: '检查', message: '检查当前记录' }
    const { result } = renderHook(() => useChatActions({
      runtime: runtime as unknown as ChatRuntime,
      props: v2Props({ onInteraction, onFeedback }),
      messages: [message],
      hostState: testHostState,
      clearWorkspaceReferences: vi.fn()
    }))

    act(() => {
      result.current.feedback(message, 'positive')
      result.current.regenerate(message.id)
      result.current.suggestion(suggestion)
      result.current.stop()
      result.current.confirmTool(tool, true)
      result.current.undoTool(tool)
    })
    expect(onFeedback).toHaveBeenCalledWith(message, 'positive')
    expect(runtime.regenerate).toHaveBeenCalledWith(message.id)
    expect(runtime.send).toHaveBeenCalledWith(suggestion.message)
    expect(runtime.stop).toHaveBeenCalledOnce()
    expect(runtime.confirmTool).toHaveBeenCalledWith(tool, true)
    expect(runtime.undoTool).toHaveBeenCalledWith(tool)
  })
})
