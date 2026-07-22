import type { ChatMessage, ChatRole, ToolCall } from '../types'
import { asText, toolCallId, toolName, visibleMessages } from '../runtime/utils'
import { getBuiltInToolPresentation } from './builtInToolPresentation'

const ACTIVE_TOOL_STATUSES = new Set(['pending', 'running', 'needs_confirmation'])

export type ToolGroupStatus =
  | 'needs_confirmation'
  | 'needs_selection'
  | 'running'
  | 'error'
  | 'cancelled'
  | 'ok'

export interface ToolCallGroupPresentation {
  key: string
  targetMessageId: string
  tools: ToolCall[]
  status: ToolGroupStatus
  activeToolIndex: number
  requiresAttention: boolean
}

export function getAssistantMessagePresentation(message: ChatMessage) {
  const extra = message.extra_data
  return {
    content: asText(message.content),
    reasoning: extra?.reasoning_steps || [],
    references: extra?.references || [],
    canRegenerate: Boolean(
      message.content && !message.streaming_error &&
      typeof extra?.agent_run_id === 'string' &&
      extra.agent_run_id &&
      extra.agent_run_final === true &&
      !(message.tool_calls || []).some((tool) => ACTIVE_TOOL_STATUSES.has(tool.status || 'pending'))
    )
  }
}

export function getUserMessageContent(message: ChatMessage): string {
  return asText(message.content)
}

export function normalizeMessageRole(role: ChatRole): ChatRole {
  return role === 'agent' ? 'assistant' : role
}

export function getMessageListPresentation(messages: ChatMessage[]) {
  const displayMessages = visibleMessages(messages)
  const lastAssistantIndex = displayMessages.reduce(
    (last, message, index) => normalizeMessageRole(message.role) === 'assistant' ? index : last,
    -1
  )
  return { displayMessages, lastAssistantIndex }
}

function assistantRunKey(message: ChatMessage, index: number): string {
  const runId = message.extra_data?.agent_run_id
  return typeof runId === 'string' && runId ? `run:${runId}` : `message:${message.id || index}`
}

function toolAliases(tool: ToolCall): string[] {
  const aliases: string[] = []
  if (tool.key) aliases.push(`key:${tool.key}`)
  const id = toolCallId(tool)
  if (id) aliases.push(`id:${id}`)
  return aliases
}

function mergeGroupTools(calls: ToolCall[]): ToolCall[] {
  const tools: ToolCall[] = []
  const indexes = new Map<string, number>()
  calls.forEach((tool) => {
    const aliases = toolAliases(tool)
    const existingIndex = aliases.reduce<number | undefined>(
      (found, alias) => found ?? indexes.get(alias),
      undefined
    )
    if (existingIndex === undefined) {
      const index = tools.length
      tools.push(tool)
      aliases.forEach((alias) => indexes.set(alias, index))
      return
    }
    tools[existingIndex] = { ...tools[existingIndex], ...tool }
    toolAliases(tools[existingIndex]).forEach((alias) => indexes.set(alias, existingIndex))
  })
  return tools
}

export function getToolEffectiveStatus(tool: ToolCall): ToolGroupStatus {
  if (tool.status === 'needs_confirmation' || tool.needs_confirmation) return 'needs_confirmation'
  const builtIn = getBuiltInToolPresentation(tool)
  if (
    (builtIn.kind === 'relation_search' && builtIn.result.resolution === 'ambiguous' && builtIn.result.candidates.length) ||
    (builtIn.kind === 'record_candidates' && builtIn.result.candidates.length)
  ) return 'needs_selection'
  if (!tool.status || tool.status === 'pending' || tool.status === 'running') return 'running'
  return tool.status
}

const GROUP_STATUS_PRIORITY: ToolGroupStatus[] = [
  'needs_confirmation', 'needs_selection', 'running', 'error', 'cancelled', 'ok'
]

function getToolGroupState(tools: ToolCall[]) {
  const effectiveStatuses = tools.map(getToolEffectiveStatus)
  const status = GROUP_STATUS_PRIORITY.find((candidate) => effectiveStatuses.includes(candidate)) || 'ok'
  let activeToolIndex = -1
  effectiveStatuses.forEach((candidate, index) => {
    if (candidate === 'needs_confirmation' || candidate === 'needs_selection' || candidate === 'running') {
      activeToolIndex = index
    }
  })
  return { status, activeToolIndex, requiresAttention: activeToolIndex >= 0 }
}

export function getToolCallGroups(messages: ChatMessage[]): Map<string, ToolCallGroupPresentation> {
  const visibleIds = new Set(visibleMessages(messages).map((message) => message.id))
  const grouped = new Map<string, { targetMessageId: string; calls: ToolCall[] }>()
  messages.forEach((message, index) => {
    if (normalizeMessageRole(message.role) !== 'assistant') return
    const key = assistantRunKey(message, index)
    const current = grouped.get(key) || { targetMessageId: '', calls: [] }
    if (visibleIds.has(message.id)) current.targetMessageId = message.id
    current.calls.push(...(message.tool_calls || []))
    grouped.set(key, current)
  })

  const result = new Map<string, ToolCallGroupPresentation>()
  grouped.forEach((group, key) => {
    if (!group.targetMessageId || !group.calls.length) return
    const tools = mergeGroupTools(group.calls)
    result.set(group.targetMessageId, {
      key,
      targetMessageId: group.targetMessageId,
      tools,
      ...getToolGroupState(tools)
    })
  })
  return result
}

export function getToolCallRenderKey(tool: ToolCall, index: number): string {
  return tool.key || toolCallId(tool) || `${toolName(tool)}-${index}`
}
