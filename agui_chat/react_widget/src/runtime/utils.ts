import type { ChatMessage, ReferenceGroup, ToolCall, ToolStatus } from '../types'

export function uuid(): string {
  const cryptoValue = globalThis.crypto
  if (cryptoValue?.randomUUID) {
    return cryptoValue.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const value = (Math.random() * 16) | 0
    const next = char === 'x' ? value : (value & 0x3) | 0x8
    return next.toString(16)
  })
}

export function clone<T>(value: T): T {
  if (value === undefined || value === null) {
    return value
  }
  return JSON.parse(JSON.stringify(value)) as T
}

export function asText(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }
  if (Array.isArray(value)) {
    return value
      .map((part) => {
        if (typeof part === 'string') {
          return part
        }
        if (part && typeof part === 'object') {
          const item = part as Record<string, unknown>
          return item.text ?? item.content ?? item.value ?? ''
        }
        return ''
      })
      .join('')
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return value === undefined || value === null ? '' : String(value)
}

export function textSummary(value: unknown, limit = 80): string {
  const text = asText(value).replace(/\s+/g, ' ').trim()
  if (!limit || text.length <= limit) {
    return text
  }
  return `${text.slice(0, limit - 1)}...`
}

export function parseJson(value: unknown): unknown {
  if (!value || typeof value !== 'string') {
    return value || {}
  }
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

export function shortHash(value: unknown): string {
  let text = ''
  let result = 0
  try {
    text = JSON.stringify(value)
  } catch {
    text = String(value || '')
  }
  for (let index = 0; index < text.length; index += 1) {
    result = (result << 5) - result + text.charCodeAt(index)
    result &= result
  }
  return (result >>> 0).toString(36)
}

export function statusFromResult(result: unknown, fallback: ToolStatus = 'pending'): ToolStatus {
  const value = result && typeof result === 'object' ? (result as Record<string, unknown>) : {}
  if (value.cancelled) {
    return 'cancelled'
  }
  if (value.needs_confirmation) {
    return 'needs_confirmation'
  }
  if (value.ok === false || value.error) {
    return 'error'
  }
  if (value.ok === true) {
    return 'ok'
  }
  return fallback
}

function statusRank(status?: ToolStatus): number {
  return (
    {
      pending: 1,
      running: 2,
      needs_confirmation: 3,
      ok: 4,
      error: 4,
      cancelled: 4
    }[status || 'pending'] || 1
  )
}

export function mergeStatus(existing?: ToolStatus, incoming?: ToolStatus): ToolStatus {
  if (!existing) {
    return incoming || 'pending'
  }
  if (!incoming) {
    return existing
  }
  return statusRank(incoming) >= statusRank(existing) ? incoming : existing
}

export function toolCallId(tool: ToolCall): string {
  return String(tool.id || tool.tool_call_id || tool.toolCallId || '')
}

export function toolName(tool: ToolCall): string {
  return String(tool.name || tool.tool_name || tool.tool || 'unknown')
}

export function toolArgs(tool: ToolCall): unknown {
  return tool.args ?? tool.tool_args ?? parseJson(tool.argsText || '{}')
}

export function toolKey(tool: ToolCall): string {
  const id = toolCallId(tool)
  const name = toolName(tool)
  const args = toolArgs(tool)
  if (id) {
    return `id:${id}`
  }
  if (tool.createdAt || tool.created_at) {
    return `created:${name}:${tool.createdAt || tool.created_at}`
  }
  return `sig:${name}:${shortHash(args)}`
}

export function normalizeReferenceGroups(value: unknown): ReferenceGroup[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((rawGroup) => {
      const group = rawGroup && typeof rawGroup === 'object' ? (rawGroup as Record<string, unknown>) : {}
      const source = Array.isArray(group.references) ? group.references : [group]
      const references = source
        .map((rawReference) => {
          const reference =
            rawReference && typeof rawReference === 'object'
              ? (rawReference as Record<string, unknown>)
              : {}
          const content =
            reference.content || reference.text || reference.summary || reference.description || ''
          const name = reference.name || reference.title || reference.url || ''
          const url = reference.url || reference.link || ''
          if (!content && !name && !url) {
            return null
          }
          return {
            name: String(name || textSummary(content, 60)),
            url: url ? String(url) : undefined,
            content: textSummary(content, 180),
            meta_data:
              reference.meta_data && typeof reference.meta_data === 'object'
                ? (reference.meta_data as Record<string, unknown>)
                : undefined
          }
        })
        .filter(Boolean)
      if (!references.length) {
        return null
      }
      return {
        query: group.query ? String(group.query) : '',
        references
      }
    })
    .filter(Boolean) as ReferenceGroup[]
}

export function visibleMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((message) => {
    if (message.hidden) {
      return false
    }
    if (message.role === 'tool' && (message.toolCallId || message.tool_call_id)) {
      return false
    }
    return true
  })
}
