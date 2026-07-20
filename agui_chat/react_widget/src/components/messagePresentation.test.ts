import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '../types'
import {
  getAssistantMessagePresentation,
  getMessageListPresentation,
  getToolCallRenderKey,
  getUserMessageContent,
  normalizeMessageRole
} from './messagePresentation'

describe('消息展示模型', () => {
  it('归一化助手正文、推理、引用和重新生成资格', () => {
    const message: ChatMessage = {
      id: 'assistant-1',
      role: 'assistant',
      content: ['最终', '回答'],
      extra_data: {
        agent_run_id: 'run-1',
        agent_run_final: true,
        reasoning_steps: [{ title: '读取上下文' }],
        references: [{ query: '客户', references: [] }]
      }
    }

    expect(getAssistantMessagePresentation(message)).toEqual({
      content: '最终回答',
      reasoning: [{ title: '读取上下文' }],
      references: [{ query: '客户', references: [] }],
      canRegenerate: true
    })
  })

  it('存在流式错误、未完成运行或活动工具时禁止重新生成', () => {
    const base: ChatMessage = {
      id: 'assistant-1',
      role: 'assistant',
      content: '回答',
      extra_data: { agent_run_id: 'run-1', agent_run_final: true }
    }

    expect(getAssistantMessagePresentation({ ...base, streaming_error: '连接中断' }).canRegenerate).toBe(false)
    expect(getAssistantMessagePresentation({ ...base, extra_data: { agent_run_id: 'run-1' } }).canRegenerate).toBe(false)
    expect(getAssistantMessagePresentation({
      ...base,
      tool_calls: [{ id: 'tool-1', status: 'running' }]
    }).canRegenerate).toBe(false)
  })

  it('过滤隐藏和独立工具消息并定位最后一条助手消息', () => {
    const assistant = { id: 'assistant-1', role: 'assistant' as const, content: '回答' }
    const agent = { id: 'agent-1', role: 'agent' as const, content: '补充' }
    const result = getMessageListPresentation([
      { id: 'user-1', role: 'user', content: '问题' },
      assistant,
      { id: 'hidden', role: 'assistant', content: '隐藏', hidden: true },
      { id: 'tool-1', role: 'tool', toolCallId: 'call-1' },
      agent
    ])

    expect(result.displayMessages).toEqual([
      { id: 'user-1', role: 'user', content: '问题' },
      assistant,
      agent
    ])
    expect(result.lastAssistantIndex).toBe(2)
    expect(normalizeMessageRole('agent')).toBe('assistant')
  })

  it('统一用户正文和工具渲染键', () => {
    expect(getUserMessageContent({ id: 'user-1', role: 'user', content: ['打开', '客户'] })).toBe('打开客户')
    expect(getToolCallRenderKey({ key: 'stable', id: 'call-1' }, 0)).toBe('stable')
    expect(getToolCallRenderKey({ id: 'call-1' }, 0)).toBe('call-1')
    expect(getToolCallRenderKey({ name: 'custom.audit' }, 2)).toBe('custom.audit-2')
  })
})
