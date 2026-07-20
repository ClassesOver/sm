import type { ChatMessage, ChatRole, ToolCall } from '../types'
import { asText, toolCallId, toolName, visibleMessages } from '../runtime/utils'

const ACTIVE_TOOL_STATUSES = new Set(['pending', 'running', 'needs_confirmation'])

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

export function getToolCallRenderKey(tool: ToolCall, index: number): string {
  return tool.key || toolCallId(tool) || `${toolName(tool)}-${index}`
}
