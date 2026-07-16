import type {
  AguiChatProps,
  AguiClientTool,
  ChatMessage,
  OdooHostSnapshot,
  ToolCall
} from '../types'
import { AGUI_ODOO_PROTOCOL } from '../types'
import { asText, clone, parseJson, toolArgs, toolCallId, toolName, uuid } from './utils'

export interface RunStateEnvelope {
  protocol: typeof AGUI_ODOO_PROTOCOL
  host: OdooHostSnapshot
  agent: Record<string, unknown>
}

export interface RunInput {
  threadId: string
  runId: string
  requestId: string
  messages: unknown[]
  tools: AguiClientTool[]
  context: Array<{ description: string; value: string }>
  forwardedProps: Record<string, never>
  state: RunStateEnvelope
  resume: unknown[]
  agentId?: string
}

export function endpoint(props: Pick<AguiChatProps, 'runtimeUrl' | 'allowCrossOriginDev'>): string {
  const value = String(props.runtimeUrl || '').trim()
  if (!value) {
    throw new Error('AG-UI runtime is not configured.')
  }
  if (value.startsWith('/') && !value.startsWith('//') && !value.includes('://')) {
    return value
  }
  if (props.allowCrossOriginDev && /^https?:\/\//i.test(value)) {
    return value
  }
  throw new Error('AG-UI runtime URL is not allowed.')
}

export function transportError(status: number): Error {
  const messages: Record<number, string> = {
    401: 'Authentication expired. Sign in again.',
    403: 'You do not have permission to run this agent.',
    429: 'Too many requests. Try again later.'
  }
  return new Error(messages[status] || `AG-UI request failed (HTTP ${status}).`)
}

export function validateHandshake(props: AguiChatProps): void {
  const handshake = props.handshake
  if (!handshake || handshake.protocol !== AGUI_ODOO_PROTOCOL) {
    throw new Error('Odoo AG-UI protocol handshake failed.')
  }
  if (handshake.agentProtocol !== AGUI_ODOO_PROTOCOL) {
    throw new Error('AgentOS AG-UI protocol handshake failed.')
  }
  if (
    !handshake.moduleVersion ||
    handshake.moduleVersion !== handshake.bundleVersion ||
    handshake.bundleVersion !== handshake.agentBundleVersion
  ) {
    throw new Error('AG-UI module, bundle, and AgentOS versions do not match.')
  }
  if (
    !/^[a-f0-9]{64}$/.test(handshake.commandCatalogHash || '') ||
    handshake.commandCatalogHash !== handshake.agentCommandCatalogHash
  ) {
    throw new Error('AG-UI command catalogs do not match.')
  }
  if (!props.hostState || props.hostState.protocol !== AGUI_ODOO_PROTOCOL) {
    throw new Error('Odoo host snapshot protocol does not match the runtime.')
  }
}

function normalizeToolCalls(toolCalls: ToolCall[] | unknown[] | undefined): unknown[] {
  return (toolCalls || [])
    .map((rawTool) => {
      const tool = rawTool as ToolCall & {
        function?: { name?: string; arguments?: unknown }
        type?: string
      }
      const id = toolCallId(tool)
      const fn = tool.function || {}
      const name = fn.name || toolName(tool)
      const args = fn.arguments ?? toolArgs(tool)
      if (!id || !name) return null
      return {
        id,
        type: tool.type || 'function',
        function: {
          name: String(name),
          arguments: typeof args === 'string' ? args : JSON.stringify(args || {})
        }
      }
    })
    .filter(Boolean)
}

function transportMessage(message: ChatMessage): unknown {
  const role = message.role === 'agent' ? 'assistant' : message.role
  if (role === 'assistant') {
    const transported: Record<string, unknown> = { id: message.id, role: 'assistant' }
    if (message.content) transported.content = asText(message.content)
    const toolCalls = normalizeToolCalls(
      message.toolCalls && message.toolCalls.length ? message.toolCalls : message.tool_calls
    )
    if (toolCalls.length) transported.toolCalls = toolCalls
    return transported
  }
  if (role === 'tool') {
    return {
      id: message.id,
      role: 'tool',
      content: asText(message.content),
      toolCallId: String(message.toolCallId || message.tool_call_id || '')
    }
  }
  if (role === 'reasoning' || role === 'system' || role === 'developer') {
    return { id: message.id, role, content: asText(message.content) }
  }
  return {
    id: message.id,
    role: 'user',
    content:
      typeof message.content === 'string' || Array.isArray(message.content)
        ? message.content
        : asText(message.content),
    ...(message.attachments?.length ? { attachments: clone(message.attachments) } : {})
  }
}

function contextValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function agentHostContext(host: OdooHostSnapshot): Record<string, unknown> {
  const action = host.action && typeof host.action === 'object'
    ? host.action as Record<string, unknown>
    : null
  return {
    protocol: host.protocol,
    snapshotId: host.snapshotId,
    hostRevision: host.hostRevision,
    interactive: host.interactive,
    surface: host.surface,
    controller: clone(host.controller),
    action: action ? {
      id: action.id,
      xmlId: action.xmlId,
      name: action.name,
      type: action.type,
      resModel: action.resModel,
      resId: action.resId,
      viewMode: action.viewMode,
      domain: action.domain,
      context: action.context,
      target: action.target
    } : false,
    menu: clone(host.menu),
    record: clone(host.record),
    selection: clone(host.selection),
    fields: clone(host.fields),
    capabilities: clone(host.capabilities)
  }
}

function normalizeRunContext(
  props: AguiChatProps,
  messages: ChatMessage[]
): Array<{ description: string; value: string }> {
  const context: Array<{ description: string; value: string }> = [{
    description: 'Odoo host snapshot',
    value: contextValue(agentHostContext(props.hostState))
  }]
  if (Array.isArray(props.context)) {
    props.context.forEach((item, index) => {
      if (
        item && typeof item === 'object' &&
        typeof (item as Record<string, unknown>).description === 'string' &&
        typeof (item as Record<string, unknown>).value === 'string'
      ) {
        context.push(clone(item as { description: string; value: string }))
      } else {
        context.push({ description: `Context ${index + 1}`, value: contextValue(item) })
      }
    })
  } else if (props.context && typeof props.context === 'object') {
    Object.entries(props.context as Record<string, unknown>).forEach(([description, value]) => {
      context.push({ description, value: contextValue(value) })
    })
  }
  if (props.user !== undefined) {
    context.push({ description: 'Odoo user', value: contextValue(props.user) })
  }
  if (props.agentId !== undefined) {
    context.push({ description: 'Agent ID', value: props.agentId })
  }
  const latestUserMessage = [...messages].reverse().find((message) => message.role === 'user')
  if (latestUserMessage?.menuMention?.valid) {
    const mention = latestUserMessage.menuMention
    context.push({
      description: 'Selected Odoo menu',
      value: contextValue({
        menuId: mention.menuId,
        actionId: mention.actionId,
        name: mention.name,
        path: mention.path,
        fullPath: mention.fullPath
      })
    })
  }
  if (
    latestUserMessage?.recordSelection &&
    latestUserMessage.recordSelection.snapshotId === props.hostState.snapshotId &&
    latestUserMessage.recordSelection.hostRevision === props.hostState.hostRevision
  ) {
    context.push({
      description: 'Selected Odoo record candidate',
      value: contextValue(latestUserMessage.recordSelection)
    })
  }
  return context
}

export function buildRunInput(
  messages: ChatMessage[],
  props: AguiChatProps,
  threadId: string,
  pendingAssistantId: string | null,
  agentState: Record<string, unknown>
): RunInput {
  const runId = uuid()
  return {
    threadId,
    runId,
    requestId: uuid(),
    messages: messages
      .filter((message) => {
        const isPendingEmpty =
          message.id === pendingAssistantId &&
          !message.content &&
          !message.streaming_error &&
          !(message.tool_calls && message.tool_calls.length)
        return !isPendingEmpty
      })
      .map(transportMessage),
    tools: clone(props.tools || []),
    context: normalizeRunContext(props, messages),
    forwardedProps: {},
    state: {
      protocol: AGUI_ODOO_PROTOCOL,
      host: clone(props.hostState),
      agent: clone(agentState || {})
    },
    resume: clone(props.resume || []),
    agentId: props.agentId
  }
}

export function validateRunInput(input: RunInput, props: AguiChatProps): void {
  validateHandshake(props)
  const maxMessages = props.limits?.messages ?? 200
  const maxBytes = props.limits?.requestBytes ?? 2 * 1024 * 1024
  if (input.messages.length > maxMessages) {
    throw new Error(`Message limit exceeded (${maxMessages}).`)
  }
  if (new TextEncoder().encode(JSON.stringify(input)).byteLength > maxBytes) {
    throw new Error('Request is larger than the configured limit.')
  }
}

export function toolCallFromTransport(toolCall: unknown, messageId?: string): ToolCall | null {
  if (!toolCall || typeof toolCall !== 'object') return null
  const raw = toolCall as Record<string, unknown>
  const fn =
    raw.function && typeof raw.function === 'object'
      ? (raw.function as Record<string, unknown>)
      : {}
  const id = raw.id || raw.tool_call_id || raw.toolCallId
  const name = fn.name || raw.name || raw.tool_name || raw.tool
  const args = fn.arguments || raw.arguments || raw.tool_args || raw.args
  if (!id || !name) return null
  return {
    id: String(id),
    tool_call_id: String(id),
    name: String(name),
    tool_name: String(name),
    tool: String(name),
    args: parseJson(args),
    tool_args: parseJson(args),
    argsText: typeof args === 'string' ? args : JSON.stringify(args || {}),
    status: 'pending',
    message_id: messageId
  }
}
