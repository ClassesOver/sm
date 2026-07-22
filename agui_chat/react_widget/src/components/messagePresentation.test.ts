import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '../types'
import {
  getAssistantMessagePresentation,
  getMessageListPresentation,
  getToolCallGroups,
  getToolEffectiveStatus,
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

  it('按运行聚合跨消息工具并挂到最后一条可见助手消息', () => {
    const firstTool = { id: 'call-1', key: 'stable-1', name: 'odoo.open_record', status: 'running' as const }
    const result = getToolCallGroups([
      { id: 'first', role: 'assistant', content: '先读取', extra_data: { agent_run_id: 'run-1' }, tool_calls: [firstTool] },
      { id: 'hidden', role: 'assistant', hidden: true, extra_data: { agent_run_id: 'run-1' }, tool_calls: [{ id: 'call-hidden', name: 'custom.hidden', status: 'ok' }] },
      { id: 'last', role: 'agent', content: '完成', extra_data: { agent_run_id: 'run-1' }, tool_calls: [{ id: 'call-2', name: 'odoo.save_current_form', status: 'ok' }] }
    ])

    expect([...result.keys()]).toEqual(['last'])
    expect(result.get('last')).toMatchObject({
      key: 'run:run-1',
      targetMessageId: 'last',
      status: 'running',
      activeToolIndex: 0,
      requiresAttention: true
    })
    expect(result.get('last')?.tools.map((tool) => tool.id)).toEqual(['call-1', 'call-hidden', 'call-2'])
  })

  it('无运行 ID 时按单条助手消息回退', () => {
    const result = getToolCallGroups([
      { id: 'first', role: 'assistant', tool_calls: [{ id: 'call-1', status: 'ok' }] },
      { id: 'second', role: 'assistant', tool_calls: [{ id: 'call-2', status: 'error' }] }
    ])

    expect([...result.keys()]).toEqual(['first', 'second'])
    expect(result.get('first')?.key).toBe('message:first')
    expect(result.get('second')?.status).toBe('error')
  })

  it('按 ID 或 key 稳定去重并保留首次位置和最新字段', () => {
    const result = getToolCallGroups([{
      id: 'assistant', role: 'assistant', extra_data: { agent_run_id: 'run-1' }, tool_calls: [
        { id: 'call-1', key: 'tool-1', name: 'custom.first', args: { value: 1 }, status: 'running' },
        { id: 'call-2', name: 'custom.second', status: 'ok' },
        { id: 'call-1', name: 'custom.first', status: 'error', error: '失败' },
        { key: 'tool-1', name: 'custom.first', result: { ok: false }, status: 'error' },
        { name: 'custom.no-id', status: 'ok' },
        { name: 'custom.no-id', status: 'ok' }
      ]
    }])
    const tools = result.get('assistant')?.tools || []

    expect(tools.map((tool) => tool.name)).toEqual([
      'custom.first', 'custom.second', 'custom.no-id', 'custom.no-id'
    ])
    expect(tools[0]).toMatchObject({
      id: 'call-1', key: 'tool-1', args: { value: 1 }, result: { ok: false }, status: 'error', error: '失败'
    })
  })

  it('派生待确认、待选择和最终聚合状态', () => {
    expect(getToolEffectiveStatus({ status: 'needs_confirmation' })).toBe('needs_confirmation')
    expect(getToolEffectiveStatus({ status: 'cancelled' })).toBe('cancelled')
    expect(getToolEffectiveStatus({ status: 'error' })).toBe('error')
    expect(getToolEffectiveStatus({ status: 'ok', name: 'odoo.search_relation', result: {
      ok: true, operation: 'odoo.search_relation', field: 'partner_id', fieldType: 'many2one',
      relation: 'res.partner', query: '上海', relationOperation: 'set', resolution: 'ambiguous',
      snapshotId: 'snapshot-1', hostRevision: 1,
      candidates: [{ id: 1, displayName: '上海客户', selected: false }]
    } })).toBe('needs_selection')
  })
})
