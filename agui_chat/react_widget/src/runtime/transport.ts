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
  forwardedProps: {
    branch?: {
      sourceThreadId: string
      sourceRunId: string
      targetMessageId: string
    }
  }
  state: RunStateEnvelope
  resume: unknown[]
  agentId?: string
}

export function endpoint(props: Pick<AguiChatProps, 'runtimeUrl' | 'allowCrossOriginDev'>): string {
  const value = String(props.runtimeUrl || '').trim()
  if (!value) {
    throw new Error('尚未配置 AG-UI 运行服务。')
  }
  if (value.startsWith('/') && !value.startsWith('//') && !value.includes('://')) {
    return value
  }
  if (props.allowCrossOriginDev && /^https?:\/\//i.test(value)) {
    return value
  }
  throw new Error('不允许使用此 AG-UI 运行服务地址。')
}

export function transportError(status: number): Error {
  const messages: Record<number, string> = {
    401: '登录状态已过期，请重新登录。',
    403: '您没有运行此智能体的权限。',
    429: '请求过于频繁，请稍后重试。'
  }
  return new Error(messages[status] || `AG-UI 请求失败（HTTP ${status}）。`)
}

export function validateHandshake(props: AguiChatProps): void {
  const handshake = props.handshake
  if (!handshake || handshake.protocol !== AGUI_ODOO_PROTOCOL) {
    throw new Error('HRP AG-UI 协议握手失败。')
  }
  if (handshake.agentProtocol !== AGUI_ODOO_PROTOCOL) {
    throw new Error('AgentOS AG-UI 协议握手失败。')
  }
  if (
    !handshake.moduleVersion ||
    handshake.moduleVersion !== handshake.bundleVersion ||
    handshake.bundleVersion !== handshake.agentBundleVersion
  ) {
    throw new Error('AG-UI 模块、前端资源与 AgentOS 版本不匹配。')
  }
  if (
    !/^[a-f0-9]{64}$/.test(handshake.commandCatalogHash || '') ||
    handshake.commandCatalogHash !== handshake.agentCommandCatalogHash
  ) {
    throw new Error('AG-UI 命令目录不匹配。')
  }
  if (!props.hostState || props.hostState.protocol !== AGUI_ODOO_PROTOCOL) {
    throw new Error('HRP 宿主快照协议与运行服务不匹配。')
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

function menuNavigationPending(messages: ChatMessage[]): boolean {
  let userIndex = -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'user') {
      userIndex = index
      break
    }
  }
  const mention = userIndex >= 0 ? messages[userIndex].menuMention : undefined
  if (!mention?.valid) return false

  const matchingCalls = new Set<string>()
  for (const message of messages.slice(userIndex + 1)) {
    const calls = [
      ...(message.toolCalls || [])
        .map((call) => toolCallFromTransport(call, message.id))
        .filter((call): call is ToolCall => Boolean(call)),
      ...(message.tool_calls || [])
    ]
    calls.forEach((call) => {
      const args = toolArgs(call)
      const callId = toolCallId(call)
      if (
        callId &&
        toolName(call) === 'odoo.open_menu' &&
        args && typeof args === 'object' && !Array.isArray(args) &&
        Number((args as Record<string, unknown>).menuId) === mention.menuId
      ) {
        matchingCalls.add(callId)
      }
    })
    if (message.role !== 'tool' || !matchingCalls.has(String(
      message.toolCallId || message.tool_call_id || ''
    ))) {
      continue
    }
    const result = parseJson(message.content)
    if (
      result && typeof result === 'object' && !Array.isArray(result) &&
      (result as Record<string, unknown>).ok === true
    ) return false
  }
  return true
}

function agentHostContext(host: OdooHostSnapshot): Record<string, unknown> {
  const action = host.action && typeof host.action === 'object'
    ? host.action as Record<string, unknown>
    : null
  const record = host.record && typeof host.record === 'object'
    ? host.record as Record<string, unknown>
    : null
  const selection = host.selection && typeof host.selection === 'object'
    ? host.selection as Record<string, unknown>
    : null
  return {
    protocol: host.protocol,
    snapshotId: host.snapshotId,
    hostRevision: host.hostRevision,
    interactive: host.interactive,
    surface: host.surface,
    pageTarget: {
      snapshotId: host.snapshotId,
      hostRevision: host.hostRevision
    },
    viewTarget: {
      snapshotId: host.snapshotId,
      hostRevision: host.hostRevision,
      controllerId: host.controller.controllerId,
      dataPointId: host.controller.dataPointId,
      model: record?.model || selection?.model || false,
      resId: record?.resId || false
    },
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
  const navigationPending = menuNavigationPending(messages)
  const context: Array<{ description: string; value: string }> = [{
    description: 'HRP 宿主快照',
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
        context.push({ description: `上下文 ${index + 1}`, value: contextValue(item) })
      }
    })
  } else if (props.context && typeof props.context === 'object') {
    Object.entries(props.context as Record<string, unknown>).forEach(([description, value]) => {
      context.push({ description, value: contextValue(value) })
    })
  }
  if (props.user !== undefined) {
    context.push({ description: 'HRP 用户', value: contextValue(props.user) })
  }
  if (props.agentId !== undefined) {
    context.push({ description: '智能体 ID', value: props.agentId })
  }
  const latestUserMessage = [...messages].reverse().find((message) => message.role === 'user')
  const selectedSkills = (latestUserMessage?.skills || []).filter((skill) => skill.valid)
  if (selectedSkills.length) {
    context.push({
      description: '已选智能体技能',
      value: contextValue(selectedSkills.map((skill) => ({
        id: skill.id,
        name: skill.name,
        description: skill.description
      })))
    })
  }
  const workspaceReferences = latestUserMessage?.workspaceReferences || []
  if (workspaceReferences.length) {
    context.push({
      description: '已选工作区引用',
      value: contextValue(workspaceReferences.map((reference) => ({
        path: reference.path,
        type: reference.isDirectory ? 'directory' : 'file',
        tool: reference.isDirectory ? 'workspace_list_files' : 'workspace_read_file'
      })))
    })
  }
  const mentions = (latestUserMessage?.mentions || []).filter((mention) => mention.valid)
  if (mentions.length) {
    context.push({
      description: '已选 HRP 引用',
      value: contextValue(mentions.map((mention) => ({
        kind: mention.kind,
        action: mention.action,
        token: mention.token,
        label: mention.label,
        detail: mention.detail,
        model: mention.model,
        expiresAt: mention.expiresAt
      })))
    })
  }
  if (latestUserMessage?.menuMention?.valid) {
    const mention = latestUserMessage.menuMention
    context.push({
      description: '已选 HRP 菜单',
      value: contextValue({
        menuId: mention.menuId,
        actionId: mention.actionId,
        name: mention.name,
        path: mention.path,
        fullPath: mention.fullPath,
        navigationRequired: navigationPending,
        requiredFirstTool: navigationPending ? 'odoo.open_menu' : false
      })
    })
  }
  if (
    latestUserMessage?.recordSelection &&
    latestUserMessage.recordSelection.snapshotId === props.hostState.snapshotId &&
    latestUserMessage.recordSelection.hostRevision === props.hostState.hostRevision
  ) {
    context.push({
      description: '已选 HRP 记录候选项',
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
  agentState: Record<string, unknown>,
  options: {
    runId?: string
    branch?: RunInput['forwardedProps']['branch']
  } = {}
): RunInput {
  const runId = options.runId || uuid()
  const navigationPending = menuNavigationPending(messages)
  const tools = clone(props.tools || []).filter((tool) => (
    !navigationPending || tool.name === 'odoo.open_menu'
  ))
  const transportMessages = messages.filter((message) => {
    const isPendingEmpty =
      message.id === pendingAssistantId &&
      !message.content &&
      !message.streaming_error &&
      !(message.tool_calls && message.tool_calls.length)
    return !isPendingEmpty
  })
  let runMessages: ChatMessage[] = []
  if (transportMessages[transportMessages.length - 1]?.role === 'tool') {
    let firstTool = transportMessages.length - 1
    while (firstTool > 0 && transportMessages[firstTool - 1].role === 'tool') firstTool -= 1
    runMessages = transportMessages.slice(firstTool)
  } else {
    const latestUser = [...transportMessages].reverse().find((message) => message.role === 'user')
    if (latestUser) runMessages = [latestUser]
  }
  return {
    threadId,
    runId,
    requestId: uuid(),
    messages: runMessages.map(transportMessage),
    tools,
    context: normalizeRunContext(props, messages),
    forwardedProps: options.branch ? { branch: clone(options.branch) } : {},
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
    throw new Error(`消息数量超过限制（${maxMessages}）。`)
  }
  if (new TextEncoder().encode(JSON.stringify(input)).byteLength > maxBytes) {
    throw new Error('请求大小超过配置限制。')
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
