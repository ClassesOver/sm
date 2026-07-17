import type {
  AguiChatProps,
  AttachmentRef,
  ChatMessage,
  HostBridgeToolCall,
  LoadedSession,
  MenuMention,
  RecordCandidate,
  RecordSelection,
  RelationCandidate,
  RuntimeSnapshot,
  SessionEntry,
  ToolCall,
  TransportState
} from '../types'
import { AGUI_ODOO_PROTOCOL } from '../types'
import { applyJsonPatch, deepMerge } from './jsonPatch'
import { buildRunInput, endpoint, toolCallFromTransport, transportError, validateRunInput } from './transport'
import {
  asText,
  clone,
  mergeStatus,
  normalizeReferenceGroups,
  parseJson,
  statusFromResult,
  textSummary,
  toolArgs,
  toolCallId,
  toolKey,
  toolName,
  uuid
} from './utils'

type Listener = () => void

type RunContext = {
  threadId: string
  controller: AbortController
  cancelled: boolean
  finalized: boolean
  savePromise: Promise<void> | null
  currentRunId: string
  currentRequestId: string
  activeClientTools: Set<string>
  receivedTerminalEvent: boolean
  upstreamError: string
  pendingHostBridgePromises: Promise<unknown>[]
  hostBridgeFollowupNeeded: boolean
}

function eventText(event: Record<string, unknown>): string {
  return String(event.delta || event.content || event.text || '')
}

function eventData(event: Record<string, unknown>): Record<string, unknown> {
  return event.data && typeof event.data === 'object'
    ? (event.data as Record<string, unknown>)
    : event
}

function eventType(event: Record<string, unknown>): string {
  return String(event.type || event.event || '')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isStateEnvelope(value: unknown): value is Record<string, unknown> & {
  agent: Record<string, unknown>
} {
  return isRecord(value) && value.protocol === AGUI_ODOO_PROTOCOL &&
    isRecord(value.host) && isRecord(value.agent)
}

function isLegacySnapshotWrapper(value: Record<string, unknown>): boolean {
  const allowedKeys = new Set(['snapshot', 'type', 'timestamp', 'rawEvent'])
  return Object.keys(value).every((key) => allowedKeys.has(key)) &&
    isStateEnvelope(value.snapshot)
}

function needsAgentStateCleanup(value: unknown): boolean {
  return isStateEnvelope(value) || isRecord(value) && isLegacySnapshotWrapper(value)
}

function normalizeAgentState(value: unknown): Record<string, unknown> {
  let current = value
  while (isRecord(current)) {
    if (isStateEnvelope(current)) {
      current = current.agent
    } else if (isLegacySnapshotWrapper(current)) {
      current = (current.snapshot as Record<string, unknown>).agent
    } else {
      break
    }
  }
  return isRecord(current) ? clone(current) : {}
}

function eventToolCallId(event: Record<string, unknown>): string {
  return String(event.toolCallId || event.tool_call_id || event.id || '')
}

function eventToolCallName(event: Record<string, unknown>): string {
  return String(event.toolCallName || event.tool_call_name || event.name || event.tool || '')
}

function normalizeReasoningSteps(value: unknown, fallbackContent?: unknown) {
  const source = Array.isArray(value) && value.length ? value : fallbackContent ? [fallbackContent] : []
  return source.map((step) => {
    if (typeof step === 'string') {
      return {
        title: textSummary(step, 80) || 'Reasoning',
        content: step
      }
    }
    const raw = step && typeof step === 'object' ? (step as Record<string, unknown>) : {}
    const content = raw.content || raw.reasoning || raw.text || raw.action || ''
    return {
      title: String(raw.title || textSummary(content || raw, 80) || 'Reasoning'),
      content: typeof content === 'string' ? content : textSummary(content, 240),
      action: raw.action ? String(raw.action) : undefined,
      result: raw.result ? String(raw.result) : undefined,
      reasoning: raw.reasoning ? String(raw.reasoning) : undefined
    }
  })
}

function sessionListFromResult(result: unknown): SessionEntry[] {
  if (Array.isArray(result)) {
    return result as SessionEntry[]
  }
  if (result && typeof result === 'object' && Array.isArray((result as { sessions?: unknown[] }).sessions)) {
    return (result as { sessions: SessionEntry[] }).sessions
  }
  return []
}

function sessionFromResult(result: unknown): LoadedSession {
  if (result && typeof result === 'object' && (result as { session?: LoadedSession }).session) {
    return (result as { session: LoadedSession }).session
  }
  return (result || {}) as LoadedSession
}

function mergeMessagesById(remote: ChatMessage[], local: ChatMessage[]): ChatMessage[] {
  const localById = new Map(local.map((message) => [message.id, message]))
  const merged = remote.map((message) => localById.get(message.id) || message)
  const remoteIds = new Set(remote.map((message) => message.id))
  local.forEach((message) => {
    if (!remoteIds.has(message.id)) merged.push(message)
  })
  return merged
}

export class ChatRuntime {
  private props: AguiChatProps

  private listeners = new Set<Listener>()

  private messages: ChatMessage[] = []

  private sessions: SessionEntry[] = []

  private session: LoadedSession | null = null

  private agentState: Record<string, unknown> = {}

  private threadId: string

  private running = false

  private transportState: TransportState | null = null

  private currentRunId = ""

  private currentRequestId = ""

  private activeRunContext: RunContext | null = null

  private loadingSessions = false

  private error = ''

  private pendingAssistantId: string | null = null

  private activeTextMessageId: string | null = null

  private activeToolCallId: string | null = null

  private toolsByKey: Record<string, ToolCall> = {}

  private executedHostBridgeTools: Record<string, boolean> = {}

  private confirmingHostBridgeTools: Record<string, boolean> = {}

  private resumedToolResults: Record<string, boolean> = {}

  private undoInFlight: Record<string, boolean> = {}

  private saveTimer: ReturnType<typeof setTimeout> | null = null

  private saveQueue: Promise<void> = Promise.resolve()

  constructor(props: AguiChatProps) {
    this.props = props
    const initialSession = props.session?.protocol === AGUI_ODOO_PROTOCOL ? props.session : null
    const storedAgentState = initialSession?.agentState || props.agentState || {}
    this.threadId = props.threadId || initialSession?.thread_id || uuid()
    this.agentState = normalizeAgentState(storedAgentState)
    this.messages = this.normalizeStoredMessages(props.initialMessages || initialSession?.messages || [])
    this.sessions = props.sessions || []
    this.session = initialSession
    try {
      endpoint(props)
    } catch (error) {
      this.error = (error as Error).message
    }
    this.initSessions()
    if (initialSession && needsAgentStateCleanup(storedAgentState)) {
      this.scheduleSave()
    }
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot(): RuntimeSnapshot {
    return {
      messages: this.messages,
      sessions: this.sessions,
      session: this.session,
      hostState: this.props.hostState,
      agentState: this.agentState,
      threadId: this.threadId,
      running: this.running,
      transportState: this.transportState,
      loadingSessions: this.loadingSessions,
      error: this.error
    }
  }

  update(nextProps: Partial<AguiChatProps> = {}): void {
    const previousThreadId = this.threadId
    const previousSessionId = this.session?.id
    this.props = { ...this.props, ...nextProps }

    if (nextProps.sessions) {
      this.sessions = nextProps.sessions
    }
    if (nextProps.session && nextProps.session.id !== previousSessionId) {
      this.applyLoadedSession(nextProps.session)
    } else if (nextProps.threadId && nextProps.threadId !== previousThreadId) {
      this.resetThread(nextProps.threadId, nextProps.initialMessages || [])
    }
    if (nextProps.menuOptions && this.revalidateMenuMentions()) {
      this.notifyMessages()
      this.scheduleSave()
    }
    this.emit()
  }

  cancel(): void {
    const context = this.activeRunContext
    if (context) this.cancelRun(context)
  }

  unmount(): void {
    this.cancel()
    if (this.saveTimer) {
      clearTimeout(this.saveTimer)
      this.saveTimer = null
    }
    this.listeners.clear()
  }

  async newSession(): Promise<void> {
    this.cancel()
    const bridge = this.props.hostBridge || {}
    if (!bridge.createSession) {
      this.resetThread(uuid(), [])
      this.session = null
      this.props.onSessionChange?.(null)
      this.emit()
      return
    }
    this.loadingSessions = true
    this.emit()
    try {
      const result = await bridge.createSession({
        surface: this.props.surface || 'dock',
        agent_id: this.props.agentId || false
      })
      const session = sessionFromResult(result)
      this.applyLoadedSession(session)
      await this.refreshSessions()
    } finally {
      this.loadingSessions = false
      this.emit()
    }
  }

  async loadSession(sessionId: string | number): Promise<void> {
    this.cancel()
    const bridge = this.props.hostBridge || {}
    if (!bridge.loadSession) {
      return
    }
    this.loadingSessions = true
    this.emit()
    try {
      const session = sessionFromResult(await bridge.loadSession(sessionId))
      this.applyLoadedSession(session)
    } finally {
      this.loadingSessions = false
      this.emit()
    }
  }

  async refreshSessions(): Promise<void> {
    const bridge = this.props.hostBridge || {}
    if (!bridge.listSessions) {
      return
    }
    this.loadingSessions = true
    this.emit()
    try {
      this.sessions = sessionListFromResult(await bridge.listSessions())
    } finally {
      this.loadingSessions = false
      this.emit()
    }
  }

  async send(
    content: string,
    attachments: AttachmentRef[] = [],
    menuMention?: MenuMention,
    recordSelection?: RecordSelection
  ): Promise<void> {
    const text = content.trim()
    const currentMenu = menuMention ? this.resolveMenuMention(menuMention) : undefined
    if (menuMention && !currentMenu) {
      const error = new Error('所选菜单已失效或无权访问，请重新选择。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return
    }
    if (recordSelection && !this.isCurrentRecordSelection(recordSelection)) {
      const error = new Error('记录候选已过期，请重新筛选。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return
    }
    if ((!text && !attachments.length && !currentMenu && !recordSelection) || this.running || this.loadingSessions) {
      return
    }
    try {
      endpoint(this.props)
    } catch (error) {
      this.error = (error as Error).message
      this.props.onError?.(error)
      this.emit()
      return
    }
    await this.ensureSession()

    this.messages.push({
      id: uuid(),
      role: 'user',
      content: text,
      attachments: clone(attachments),
      menuMention: currentMenu,
      recordSelection: recordSelection ? clone(recordSelection) : undefined,
      created_at: Date.now()
    })
    this.pendingAssistantId = uuid()
    this.messages.push({
      id: this.pendingAssistantId,
      role: 'assistant',
      content: '',
      tool_calls: [],
      created_at: Date.now()
    })
    this.executedHostBridgeTools = {}
    this.confirmingHostBridgeTools = {}
    this.resumedToolResults = {}
    this.undoInFlight = {}
    const context = this.createRunContext()
    await this.executeRunLifecycle(context, () => this.run(context, 0))
  }

  stop(): void {
    this.cancel()
  }

  async confirmTool(tool: ToolCall, approved: boolean): Promise<void> {
    const bridge = this.props.hostBridge
    const key = toolKey(tool)
    const current = this.toolsByKey[key] || tool
    const result = current.result && typeof current.result === 'object'
      ? current.result as Record<string, unknown> : {}
    const authorizationId = String(result.authorization_id || tool.confirmation_id || '')
    if (
      !bridge?.confirmTool || !authorizationId || this.running ||
      current.status !== 'needs_confirmation' || this.confirmingHostBridgeTools[key]
    ) return
    const call: HostBridgeToolCall = {
      id: toolCallId(current) || false, tool: toolName(current),
      arguments: toolArgs(current), message_id: current.message_id || false,
      context: { requestId: this.currentRequestId, runId: this.currentRunId, threadId: this.threadId }
    }
    this.confirmingHostBridgeTools[key] = true
    const context = this.createRunContext()
    await this.executeRunLifecycle(context, async () => {
      const resultPromise = Promise.resolve()
        .then(() => bridge.confirmTool!(call, authorizationId, approved))
        .then(
          (value) => this.normalizeHostBridgeSuccess(current, value),
          (error): Record<string, unknown> => ({
            ok: false,
            operation: toolName(current),
            error: (error as Error)?.message || 'Tool confirmation failed.'
          })
        )
        .then((finalResult) => {
          if (finalResult.needs_confirmation) {
            const args = isRecord(toolArgs(current))
              ? toolArgs(current) as Record<string, unknown> : {}
            const nextArgs = {
              ...args,
              ...(finalResult.target ? { target: finalResult.target } : {}),
              ...(finalResult.patch ? { patch: finalResult.patch } : {})
            }
            this.mergeTool({
              id: toolCallId(current), name: toolName(current),
              args: nextArgs, tool_args: nextArgs, result: finalResult,
              status: 'needs_confirmation', needs_confirmation: true, error: false
            })
            this.notifyMessages()
            this.emit()
          } else {
            this.recordHostBridgeResult(current, finalResult, context)
          }
          return finalResult
        })
      const persistedResult = resultPromise.then(async (finalResult) => {
        await this.persistImmediately()
        return finalResult
      })
      const finalResult = await this.awaitWithRunCancellation(context, persistedResult)
      this.throwIfRunCancelled(context)
      if (finalResult.needs_confirmation || this.resumedToolResults[key]) return
      this.resumedToolResults[key] = true
      await this.run(context, 0)
    }, () => {
      delete this.confirmingHostBridgeTools[key]
    })
  }

  async undoTool(tool: ToolCall): Promise<void> {
    const current = this.toolsByKey[toolKey(tool)] || tool
    const result = isRecord(current.result) ? current.result : {}
    const receipt = isRecord(result.receipt) ? result.receipt : {}
    const undo = isRecord(receipt.undo) ? receipt.undo : {}
    const authorizationId = String(undo.authorization_id || '')
    if (!this.props.hostBridge?.undoTool || !authorizationId ||
        undo.status === 'undone' || this.undoInFlight[authorizationId]) return
    this.undoInFlight[authorizationId] = true
    receipt.undo = { ...undo, status: 'running' }
    this.mergeTool({ ...current, result: { ...result, receipt } })
    this.notifyMessages()
    this.emit()
    try {
      const value = this.normalizeHostBridgeSuccess(
        { name: 'odoo.undo_current_form' },
        await this.props.hostBridge.undoTool(authorizationId)
      )
      const succeeded = value.ok === true && value.undone === true
      receipt.undo = {
        ...undo,
        status: succeeded ? 'undone' : 'error',
        error: succeeded ? false : value.error || value.code || 'undo_failed'
      }
      this.mergeTool({ ...current, result: { ...result, receipt, undoResult: value } })
    } catch (error) {
      receipt.undo = { ...undo, status: 'error', error: (error as Error).message }
      this.mergeTool({ ...current, result: { ...result, receipt } })
    } finally {
      delete this.undoInFlight[authorizationId]
      this.notifyMessages()
      this.emit()
      await this.persistImmediately()
    }
  }

  async selectRelationCandidates(tool: ToolCall, candidates: RelationCandidate[]): Promise<string | null> {
    if (this.running || toolName(tool) !== 'odoo.search_relation' || !candidates.length) return null
    const result = tool.result && typeof tool.result === 'object'
      ? tool.result as Record<string, unknown> : {}
    const currentHost = this.props.hostState
    if (result.snapshotId !== currentHost.snapshotId || result.hostRevision !== currentHost.hostRevision) {
      const error = new Error('关系候选已过期，请根据当前表单重新查询。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return null
    }
    const available = Array.isArray(result.candidates)
      ? result.candidates as Array<Record<string, unknown>> : []
    const availableIds = new Set(available.map((candidate) => Number(candidate.id)))
    const unique = candidates.filter((candidate, index, list) =>
      Number.isInteger(candidate.id) && candidate.id > 0 && availableIds.has(candidate.id) &&
      list.findIndex((item) => item.id === candidate.id) === index
    )
    const fieldType = String(result.fieldType || '')
    const operation = String(result.relationOperation || '')
    if (!unique.length || fieldType === 'many2one' && unique.length !== 1) return null
    const incompatible = unique.some((candidate) =>
      operation === 'link' ? candidate.selected : operation === 'unlink' ? !candidate.selected : false
    )
    if (incompatible) return null
    const selection = {
      field: String(result.field || ''),
      operation,
      records: unique.map((candidate) => ({ id: candidate.id, displayName: candidate.displayName })),
      snapshotId: String(result.snapshotId || '')
    }
    const names = unique.map((candidate) => candidate.displayName + ' (#' + candidate.id + ')').join('、')
    const content = '我选择了' + String(result.fieldLabel || result.field || '关系字段') + '：' + names +
      '。关系选择数据：' + JSON.stringify(selection)
    await this.send(content)
    return content
  }

  async selectRecordCandidate(tool: ToolCall, candidate: RecordCandidate): Promise<string | null> {
    if (this.running || toolName(tool) !== 'odoo.apply_filter') return null
    const result = isRecord(tool.result) ? tool.result : {}
    const host = this.props.hostState
    if (result.snapshotId !== host.snapshotId || result.hostRevision !== host.hostRevision) {
      const error = new Error('记录候选已过期，请重新筛选。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return null
    }
    const candidates = Array.isArray(result.candidates)
      ? result.candidates as Array<Record<string, unknown>> : []
    if (!candidates.some((item) => item.token === candidate.token)) return null
    const selection: RecordSelection = {
      token: candidate.token,
      displayName: candidate.displayName,
      snapshotId: host.snapshotId,
      hostRevision: host.hostRevision
    }
    if (!this.isCurrentRecordSelection(selection)) return null
    const content = `选择记录：${candidate.displayName}`
    await this.send(content, [], undefined, selection)
    return content
  }

  removeMenuMention(messageId: string): void {
    if (this.running) return
    const message = this.messages.find((item) => item.id === messageId && item.role === 'user')
    if (!message?.menuMention) return
    delete message.menuMention
    this.notifyMessages()
    this.scheduleSave()
    this.emit()
  }

  async regenerate(messageId: string): Promise<void> {
    if (this.running) {
      return
    }
    const assistantIndex = this.messages.findIndex(
      (message) =>
        message.id === messageId && (message.role === 'assistant' || message.role === 'agent')
    )
    if (assistantIndex < 0) {
      return
    }
    let userIndex = assistantIndex - 1
    while (userIndex >= 0 && this.messages[userIndex].role !== 'user') {
      userIndex -= 1
    }
    if (userIndex < 0) {
      return
    }
    const userMessage = this.messages[userIndex]
    if (userMessage.menuMention && !this.resolveMenuMention(userMessage.menuMention)) {
      const error = new Error('消息中的菜单已失效，无法重新执行。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return
    }
    if (userMessage.recordSelection && !this.isCurrentRecordSelection(userMessage.recordSelection)) {
      const error = new Error('消息中的记录候选已过期，请重新筛选。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return
    }
    this.messages = this.messages.slice(0, userIndex + 1)
    this.pendingAssistantId = uuid()
    this.messages.push({
      id: this.pendingAssistantId,
      role: 'assistant',
      content: '',
      tool_calls: [],
      created_at: Date.now()
    })
    this.executedHostBridgeTools = {}
    this.confirmingHostBridgeTools = {}
    this.resumedToolResults = {}
    this.undoInFlight = {}
    const context = this.createRunContext()
    await this.executeRunLifecycle(context, () => this.run(context, 0))
  }

  async uploadAttachment(file: File, onProgress?: (progress: number) => void): Promise<AttachmentRef> {
    await this.ensureSession()
    if (!this.session) {
      throw new Error('A chat session is required to upload attachments.')
    }
    const sessionId = String(this.session.id || '')
    if (!/^\d+$/.test(sessionId)) {
      throw new Error('当前聊天会话不可用。')
    }
    return new Promise((resolve, reject) => {
      const form = new FormData()
      form.append('chat_session_id', sessionId)
      form.append('file', file)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/agui_chat/attachment/upload')
      xhr.withCredentials = true
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress?.(Math.round((event.loaded / event.total) * 100))
        }
      }
      xhr.onerror = () => reject(new Error('Attachment upload failed.'))
      xhr.onload = () => {
        let payload: { attachment?: AttachmentRef; error?: string } = {}
        try {
          payload = JSON.parse(xhr.responseText || '{}')
        } catch (_error) {
          reject(new Error('Invalid attachment upload response.'))
          return
        }
        if (xhr.status < 200 || xhr.status >= 300 || !payload.attachment) {
          reject(new Error(payload.error || 'Attachment upload failed.'))
          return
        }
        onProgress?.(100)
        resolve(payload.attachment)
      }
      xhr.send(form)
    })
  }

  async deleteAttachment(attachmentId: string): Promise<void> {
    const response = await fetch('/agui_chat/attachment/delete', {
      method: 'POST',
      credentials: this.props.credentials || 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ attachment_id: attachmentId })
    })
    if (!response.ok) {
      throw new Error('Attachment deletion failed.')
    }
  }

  applyEvent(rawEvent: unknown): void {
    this.applyEventForContext(rawEvent, this.activeRunContext)
  }

  private applyEventForContext(rawEvent: unknown, context: RunContext | null): void {
    if (!rawEvent || typeof rawEvent !== 'object') {
      return
    }
    if (context?.cancelled) return
    const event = rawEvent as Record<string, unknown>
    const eventRunId = String(event.runId || event.run_id || "")
    const eventThreadId = String(event.threadId || event.thread_id || "")
    const expectedRunId = context?.currentRunId || this.currentRunId
    const expectedThreadId = context?.threadId || this.threadId
    if ((eventRunId && eventRunId !== expectedRunId) ||
        (eventThreadId && eventThreadId !== expectedThreadId)) {
      return
    }
    const type = eventType(event)
    const data = eventData(event)
    let tool: ToolCall | null
    this.props.onEvent?.(event)

    if (type === 'TEXT_MESSAGE_START') {
      this.activeTextMessageId = String(event.messageId || event.message_id || '')
      this.ensureAssistant(this.activeTextMessageId || undefined)
    } else if (type === 'TEXT_MESSAGE_CONTENT' || type === 'TEXT_MESSAGE_CHUNK') {
      this.appendAssistantContent(eventText(event), String(event.messageId || event.message_id || this.activeTextMessageId || ''))
    } else if (type === 'TEXT_MESSAGE_END') {
      this.activeTextMessageId = null
    } else if (type === 'TOOL_CALL_START') {
      this.activeToolCallId = eventToolCallId(event)
      this.mergeTool({
        id: this.activeToolCallId,
        name: eventToolCallName(event),
        argsText: '',
        args: {},
        status: 'running',
        parentMessageId: String(event.parentMessageId || event.parent_message_id || '')
      })
    } else if (type === 'TOOL_CALL_ARGS' || type === 'TOOL_CALL_CHUNK') {
      tool = this.mergeTool({
        id: eventToolCallId(event) || this.activeToolCallId || '',
        name: eventToolCallName(event),
        status: 'running'
      })
      tool.argsText = `${tool.argsText || ''}${String(event.delta || event.args || event.toolCallArgs || '')}`
      tool.args = parseJson(tool.argsText)
      tool.tool_args = tool.args
    } else if (type === 'TOOL_CALL_END') {
      tool = this.mergeTool({
        id: eventToolCallId(event) || this.activeToolCallId || '',
        name: eventToolCallName(event),
        status: 'pending'
      })
      this.activeToolCallId = null
      this.executeHostBridgeTool(tool, context)
    } else if (type === 'TOOL_CALL_RESULT') {
      this.applyToolResult(event)
    } else if (type === 'RUN_ERROR') {
      const message = String(data.message || data.content || event.message || 'AG-UI run failed.')
      if (context) {
        context.upstreamError = message
        context.receivedTerminalEvent = true
      }
      this.recordRunError(message)
    } else if (type === 'RUN_FINISHED') {
      if (context) context.receivedTerminalEvent = true
      this.applyRunFinished(event)
    } else if (type === 'REASONING_START' || type === 'REASONING_MESSAGE_START') {
      this.ensureAssistant()
    } else if (type === 'REASONING_MESSAGE_CONTENT' || type === 'REASONING_MESSAGE_CHUNK') {
      this.appendReasoning(eventText(event))
    } else if (type === 'REASONING_MESSAGE_END' || type === 'REASONING_END') {
      this.ensureAssistant()
    } else if (type === 'STATE_SNAPSHOT' || type === 'STATE_CHANGED') {
      this.applyStateSnapshot(
        (data.snapshot || event.snapshot || data.state || event.state || data.value || data) as Record<string, unknown>
      )
    } else if (type === 'STATE_DELTA') {
      const delta = data.delta || data.value || data
      if (Array.isArray(delta)) {
        this.applyStatePatch(delta)
      } else {
        this.applyStateDelta(delta)
      }
    } else if (type === 'STATE_PATCH' || type === 'STATE_PATCHES') {
      this.applyStatePatch(data.patch || data.patches || data.value || event.patch)
    } else if (type === 'MESSAGES_SNAPSHOT' && Array.isArray(data.messages)) {
      this.mergeIncomingMessages(data.messages as ChatMessage[])
    }
    this.notifyMessages()
    this.emit()
  }

  private async initSessions(): Promise<void> {
    if (this.session || !this.props.hostBridge?.listSessions) {
      return
    }
    try {
      await this.refreshSessions()
      if (this.sessions.length && this.props.hostBridge?.loadSession) {
        await this.loadSession(this.sessions[0].id)
      } else if (!this.sessions.length && this.props.hostBridge?.createSession) {
        await this.newSession()
      }
    } catch (error) {
      this.props.onError?.(error)
    }
  }

  private async ensureSession(): Promise<void> {
    if (this.session || !this.props.hostBridge?.createSession) {
      return
    }
    await this.newSession()
  }

  private applyLoadedSession(session: LoadedSession): void {
    if (session.protocol !== AGUI_ODOO_PROTOCOL) {
      throw new Error('Unsupported chat session protocol.')
    }
    this.session = session
    this.threadId = session.thread_id || this.props.threadId || uuid()
    const storedAgentState = session.agentState || this.props.agentState || {}
    this.agentState = normalizeAgentState(storedAgentState)
    this.messages = this.normalizeStoredMessages(session.messages || [])
    this.toolsByKey = {}
    this.pendingAssistantId = null
    this.activeTextMessageId = null
    this.activeToolCallId = null
    this.executedHostBridgeTools = {}
    this.confirmingHostBridgeTools = {}
    this.resumedToolResults = {}
    this.undoInFlight = {}
    this.props.onSessionChange?.(session)
    this.notifyMessages()
    this.props.onAgentStateChange?.(this.agentState)
    if (needsAgentStateCleanup(storedAgentState)) {
      this.scheduleSave()
    }
  }

  private resetThread(threadId: string, messages: ChatMessage[]): void {
    this.cancel()
    this.threadId = threadId
    this.messages = this.normalizeStoredMessages(messages)
    this.agentState = normalizeAgentState(this.props.agentState || {})
    this.running = false
    this.pendingAssistantId = null
    this.activeTextMessageId = null
    this.activeToolCallId = null
    this.toolsByKey = {}
    this.executedHostBridgeTools = {}
    this.confirmingHostBridgeTools = {}
    this.resumedToolResults = {}
    this.undoInFlight = {}
    this.notifyMessages()
  }

  private createRunContext(): RunContext {
    const context: RunContext = {
      threadId: this.threadId,
      controller: new AbortController(),
      cancelled: false,
      finalized: false,
      savePromise: null,
      currentRunId: '',
      currentRequestId: '',
      activeClientTools: new Set(),
      receivedTerminalEvent: false,
      upstreamError: '',
      pendingHostBridgePromises: [],
      hostBridgeFollowupNeeded: false
    }
    this.activeRunContext = context
    this.running = true
    this.error = ''
    return context
  }

  private async executeRunLifecycle(
    context: RunContext,
    action: () => Promise<void>,
    cleanup?: () => void
  ): Promise<void> {
    try {
      this.props.onRunningChange?.(true)
      this.notifyMessages()
      this.emit()
      await action()
    } catch (error) {
      this.handleRunFailure(context, error)
    } finally {
      try {
        cleanup?.()
      } finally {
        const savePromise = this.finalizeRun(context)
        if (savePromise) await savePromise
      }
    }
  }

  private handleRunFailure(context: RunContext, error: unknown): void {
    if (this.activeRunContext !== context) return
    if (context.cancelled || (error as Error)?.name === 'AbortError') {
      context.cancelled = true
      this.transportState = 'cancelled'
      return
    }
    this.error = context.upstreamError || (error as Error)?.message || 'AG-UI run failed.'
    this.recordRunError(this.error)
    try {
      this.setTransportState('error')
    } catch (_callbackError) {
      // State is already updated; finalization must still restore the input.
    }
    try {
      this.props.onError?.(error)
    } catch (_callbackError) {
      // Consumer callbacks must not keep the runtime in a running state.
    }
  }

  private cancelRun(context: RunContext): void {
    if (context.cancelled) return
    context.cancelled = true
    if (!context.controller.signal.aborted) context.controller.abort()
    this.finalizeRun(context, 'cancelled')
  }

  private finalizeRun(context: RunContext, state?: TransportState): Promise<void> | null {
    if (context.finalized) return context.savePromise
    context.finalized = true
    if (this.activeRunContext !== context) return context.savePromise

    if (state) this.transportState = state
    this.activeRunContext = null
    this.pendingAssistantId = null
    this.running = false

    const callbacks: Array<() => void> = []
    if (state) callbacks.push(() => this.props.onTransportStateChange?.(state))
    callbacks.push(
      () => this.props.onRunningChange?.(false),
      () => this.notifyMessages(),
      () => this.emit()
    )
    callbacks.forEach((callback) => {
      try {
        callback()
      } catch (_callbackError) {
        // Runtime state is authoritative even when a consumer callback fails.
      }
    })
    context.savePromise = this.persistImmediately()
    return context.savePromise
  }

  private throwIfRunCancelled(context: RunContext): void {
    if (context.cancelled || context.controller.signal.aborted ||
        this.activeRunContext !== context) {
      throw new DOMException('Aborted', 'AbortError')
    }
  }

  private async awaitWithRunCancellation<T>(context: RunContext, promise: Promise<T>): Promise<T> {
    this.throwIfRunCancelled(context)
    let rejectCancelled: ((reason: DOMException) => void) | null = null
    const cancelled = new Promise<never>((_resolve, reject) => {
      rejectCancelled = reject
    })
    const onAbort = () => rejectCancelled?.(new DOMException('Aborted', 'AbortError'))
    context.controller.signal.addEventListener('abort', onAbort, { once: true })
    try {
      return await Promise.race([promise, cancelled])
    } finally {
      context.controller.signal.removeEventListener('abort', onAbort)
    }
  }

  private async run(context: RunContext, depth: number): Promise<void> {
    this.throwIfRunCancelled(context)
    context.pendingHostBridgePromises = []
    context.hostBridgeFollowupNeeded = false
    const input = buildRunInput(
      this.messages, this.props, context.threadId, this.pendingAssistantId, this.agentState
    )
    validateRunInput(input, this.props)
    context.currentRunId = input.runId
    context.currentRequestId = input.requestId
    context.activeClientTools = new Set(input.tools.map((tool) => tool.name))
    context.receivedTerminalEvent = false
    context.upstreamError = ''
    this.currentRunId = input.runId
    this.currentRequestId = input.requestId
    this.setTransportState('connecting')
    const response = await fetch(endpoint(this.props), {
      method: 'POST',
      credentials:
        this.props.credentials || (this.props.allowCrossOriginDev ? 'include' : 'same-origin'),
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        'X-Request-ID': input.requestId,
        ...(this.props.headers || {})
      },
      body: JSON.stringify(input),
      signal: context.controller.signal
    })
    if (!response.ok) {
      throw transportError(response.status)
    }
    if (!(response.headers.get("content-type") || "").includes("text/event-stream")) {
      throw new Error("AG-UI runtime must return text/event-stream.")
    }
    if (!response.body) {
      throw new Error("AG-UI SSE response has no body.")
    }
    this.setTransportState("streaming")
    await this.readSse(response.body, context)
    this.throwIfRunCancelled(context)
    if (!context.receivedTerminalEvent) {
      throw new Error("AG-UI stream ended before RUN_FINISHED.")
    }
    if (context.upstreamError) {
      throw new Error(context.upstreamError)
    }
    await this.waitForHostBridge(context, depth)
    this.throwIfRunCancelled(context)
    this.setTransportState('completed')
  }

  private async readSse(body: ReadableStream<Uint8Array>, context: RunContext): Promise<void> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const limit = this.props.limits?.sseEventBytes ?? 1024 * 1024
    try {
      for (;;) {
        const result = await reader.read()
        if (result.done) {
          buffer += decoder.decode()
          if (buffer.trim()) this.consumeSseBlock(buffer, context)
          return
        }
        buffer += decoder.decode(result.value, { stream: true })
        if (new TextEncoder().encode(buffer).byteLength > limit && !/\r?\n\r?\n/.test(buffer)) {
          throw new Error('SSE event exceeds the configured size limit.')
        }
        buffer = this.flushSse(buffer, limit, context)
        if (context.receivedTerminalEvent) {
          return
        }
        this.throwIfRunCancelled(context)
      }
    } finally {
      if (context.receivedTerminalEvent) void reader.cancel().catch(() => undefined)
      reader.releaseLock()
    }
  }

  private flushSse(buffer: string, limit: number, context: RunContext): string {
    let match = buffer.match(/\r?\n\r?\n/)
    while (match && !context.receivedTerminalEvent && !context.cancelled) {
      const block = buffer.slice(0, match.index)
      if (new TextEncoder().encode(block).byteLength <= limit) {
        this.consumeSseBlock(block, context)
      }
      buffer = buffer.slice((match.index || 0) + match[0].length)
      match = buffer.match(/\r?\n\r?\n/)
    }
    return buffer
  }

  private consumeSseBlock(block: string, context: RunContext): void {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, ''))
      .join('\n')
    if (!data || data === '[DONE]') return
    let event: unknown
    try {
      event = JSON.parse(data)
    } catch {
      this.props.onError?.(new Error('Ignored malformed SSE event.'))
      return
    }
    this.applyEventForContext(event, context)
  }

  private async waitForHostBridge(context: RunContext, depth: number): Promise<void> {
    this.throwIfRunCancelled(context)
    const pending = context.pendingHostBridgePromises
    const maxDepth = this.props.maxToolFollowups ?? 4
    context.pendingHostBridgePromises = []
    if (!pending.length) {
      return
    }
    await this.awaitWithRunCancellation(context, Promise.all(pending))
    if (context.pendingHostBridgePromises.length) {
      await this.waitForHostBridge(context, depth)
    }
    this.throwIfRunCancelled(context)
    if (context.hostBridgeFollowupNeeded && depth < maxDepth) {
      context.hostBridgeFollowupNeeded = false
      await this.run(context, depth + 1)
    } else if (context.hostBridgeFollowupNeeded) {
      context.hostBridgeFollowupNeeded = false
      this.appendAssistantContent(`\n\n已达到本轮 ${maxDepth} 次页面操作上限。请继续发送消息以完成剩余操作。`)
    }
  }

  private ensureAssistant(messageId?: string): ChatMessage {
    let message = messageId ? this.messages.find((item) => item.id === messageId) : null
    const pending = this.pendingAssistantId
      ? this.messages.find((item) => item.id === this.pendingAssistantId)
      : null
    if (
      !message &&
      messageId &&
      pending &&
      !pending.content &&
      !(pending.tool_calls && pending.tool_calls.length)
    ) {
      pending.id = messageId
      this.pendingAssistantId = messageId
      message = pending
    } else if (!message && !messageId) {
      message = this.lastAssistant()
    }
    if (!message) {
      message = {
        id: messageId || uuid(),
        role: 'assistant',
        content: '',
        tool_calls: [],
        created_at: Date.now()
      }
      this.messages.push(message)
    }
    return message
  }

  private lastAssistant(): ChatMessage | null {
    for (let index = this.messages.length - 1; index >= 0; index -= 1) {
      const message = this.messages[index]
      if (message.role === 'assistant' || message.role === 'agent') {
        return message
      }
    }
    return null
  }

  private appendAssistantContent(delta: string, messageId?: string): void {
    const message = this.ensureAssistant(messageId)
    message.content = `${asText(message.content)}${delta || ''}`
  }

  private recordRunError(message: string): void {
    this.ensureAssistant().streaming_error = message || 'AG-UI run failed.'
  }

  private mergeTool(tool: ToolCall): ToolCall {
    const key = toolKey(tool)
    const existing = this.toolsByKey[key] || {}
    const parentMessageId = String(
      tool.parentMessageId || existing.parentMessageId || tool.message_id || existing.message_id || ''
    )
    const message = this.ensureAssistant(parentMessageId || undefined)
    const cleanTool = Object.fromEntries(
      Object.entries(tool).filter(([, value]) => value !== undefined && value !== '')
    ) as ToolCall
    const name = toolName({ ...existing, ...cleanTool })
    const args = toolArgs({ ...existing, ...cleanTool })
    const id = toolCallId({ ...existing, ...cleanTool })
    const next: ToolCall = {
      ...existing,
      ...cleanTool,
      id: id || undefined,
      tool_call_id: id || undefined,
      name,
      tool_name: name,
      tool: name,
      args,
      tool_args: args,
      key,
      status: mergeStatus(existing.status, tool.status || 'pending'),
      parentMessageId: parentMessageId || message.id,
      message_id: tool.message_id || existing.message_id || message.id
    }
    this.toolsByKey[key] = next
    message.tool_calls = (message.tool_calls || []).filter((item) => (item.key || toolKey(item)) !== key)
    message.tool_calls.push(next)
    return next
  }

  private applyToolResult(event: Record<string, unknown>): void {
    const result = parseJson(event.content !== undefined ? event.content : event.result)
    this.mergeTool({
      id: eventToolCallId(event),
      name: eventToolCallName(event),
      result,
      status: statusFromResult(result, 'ok'),
      error:
        result && typeof result === 'object'
          ? ((result as Record<string, unknown>).error as string | boolean)
          : false
    })
  }

  private executeHostBridgeTool(tool: ToolCall, context: RunContext | null): void {
    if (!context || !context.activeClientTools.has(toolName(tool))) {
      return
    }
    const key = tool.key || toolKey(tool)
    if (!tool || this.executedHostBridgeTools[key]) {
      return
    }
    let promise: Promise<unknown> | null = null
    try {
      promise = this.callHostBridge(tool, context)
    } catch (error) {
      promise = Promise.reject(error)
    }
    if (!promise) {
      return
    }
    this.executedHostBridgeTools[key] = true
    this.mergeTool({
      id: toolCallId(tool),
      name: toolName(tool),
      status: 'running'
    })
    const handled = promise.then(
      (value) => {
        this.recordHostBridgeResult(tool, this.normalizeHostBridgeSuccess(tool, value), context)
      },
      (error) => {
        this.recordHostBridgeResult(tool, {
          ok: false,
          operation: toolName(tool),
          error: (error as Error)?.message || String(error || 'Host bridge failed.')
        }, context)
      }
    ).finally(() => {
      if (context.cancelled || this.activeRunContext !== context) {
        void this.persistImmediately()
      }
    })
    context.pendingHostBridgePromises.push(handled)
  }

  private callHostBridge(tool: ToolCall, context: RunContext): Promise<unknown> | null {
    const bridge = this.props.hostBridge || {}
    const args = toolArgs(tool)
    const call: HostBridgeToolCall = {
      id: toolCallId(tool) || false,
      tool: toolName(tool),
      arguments: args,
      message_id: tool.message_id || false,
      context: {
        requestId: context.currentRequestId,
        runId: context.currentRunId,
        threadId: context.threadId
      }
    }
    return bridge.executeTool ? Promise.resolve(bridge.executeTool(call)) : null
  }

  private normalizeHostBridgeSuccess(tool: ToolCall, value: unknown): Record<string, unknown> {
    if (
      value &&
      typeof value === 'object' &&
      ('ok' in value || 'operation' in value || 'applied' in value || 'rejected' in value)
    ) {
      return value as Record<string, unknown>
    }
    return {
      ok: true,
      operation: toolName(tool),
      content: value
    }
  }

  private recordHostBridgeResult(
    tool: ToolCall,
    result: Record<string, unknown>,
    context: RunContext | null = this.activeRunContext
  ): void {
    const id = toolCallId(tool)
    if (result.needs_confirmation) {
      this.mergeTool({
        id,
        name: toolName(tool),
        result,
        status: 'needs_confirmation',
        error: false
      })
      this.notifyMessages()
      this.emit()
      return
    }
    const messageId = `tool-${id || uuid()}`
    const content = JSON.stringify(result || {})
    const existing = this.messages.find((message) => message.id === messageId)
    const source = this.messages.find((message) => message.id === tool.message_id)
    this.mergeTool({
      id,
      name: toolName(tool),
      result,
      status: statusFromResult(result, 'ok'),
      needs_confirmation: false,
      error: (result.error || false) as string | boolean
    })
    if (existing) {
      existing.content = content
    } else {
      this.messages.push({
        id: messageId,
        role: 'tool',
        name: toolName(tool),
        toolCallId: id,
        tool_call_id: id,
        content,
        hidden: true,
        created_at: Date.now()
      })
    }
    if (source) {
      source.content = ''
    }
    if (context && !context.cancelled && this.activeRunContext === context) {
      context.hostBridgeFollowupNeeded = true
    }
    this.notifyMessages()
    this.emit()
  }

  private async persistImmediately(): Promise<void> {
    try {
      await this.queueSave()
    } catch (error) {
      const failure = error instanceof Error
        ? error : new Error(String(error || 'Session save failed.'))
      if (this.error === failure.message) return
      this.error = failure.message
      try {
        this.props.onError?.(failure)
      } catch (_callbackError) {
        // Persistence failures must not reactivate or block the input.
      }
      try {
        this.emit()
      } catch (_callbackError) {
        // In-memory state remains usable even when a subscriber fails.
      }
    }
  }

  private applyRunFinished(event: Record<string, unknown>): void {
    const outcome =
      event.outcome && typeof event.outcome === 'object'
        ? (event.outcome as Record<string, unknown>)
        : {}
    const interrupts = outcome.type === 'interrupt' && Array.isArray(outcome.interrupts) ? outcome.interrupts : []
    interrupts.forEach((interrupt) => {
      const value = interrupt && typeof interrupt === 'object' ? (interrupt as Record<string, unknown>) : {}
      this.mergeTool({
        id: String(value.toolCallId || value.id || ''),
        name: String(value.reason || 'interrupt'),
        status: 'needs_confirmation',
        result: value
      })
    })
  }

  private appendReasoning(content: string): void {
    const message = this.ensureAssistant()
    message.extra_data = message.extra_data || {}
    message.extra_data.reasoning_steps = message.extra_data.reasoning_steps || []
    message.extra_data.reasoning_steps.push({
      title: 'Reasoning',
      content
    })
  }

  private reportHostStateMutation(): void {
    this.props.onError?.(new Error("Ignored an agent attempt to mutate Odoo hostState."))
  }

  private extractAgentState(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return {}
    }
    const envelope = value as Record<string, unknown>
    if ("host" in envelope &&
        JSON.stringify(envelope.host) !== JSON.stringify(this.props.hostState)) {
      this.reportHostStateMutation()
    }
    if (envelope.agent && typeof envelope.agent === "object" && !Array.isArray(envelope.agent)) {
      return normalizeAgentState(envelope.agent)
    }
    const agent = { ...envelope }
    delete agent.host
    delete agent.protocol
    return normalizeAgentState(agent)
  }

  private applyStateSnapshot(state: Record<string, unknown>): void {
    this.agentState = this.extractAgentState(state)
    this.props.onAgentStateChange?.(this.agentState)
    this.scheduleSave()
  }

  private applyStateDelta(delta: unknown): void {
    this.agentState = deepMerge(this.agentState || {}, this.extractAgentState(delta))
    this.props.onAgentStateChange?.(this.agentState)
    this.scheduleSave()
  }

  private applyStatePatch(patch: unknown): void {
    if (!Array.isArray(patch)) return
    let nextState = this.agentState || {}
    patch.forEach((operation) => {
      if (!operation || typeof operation !== "object") return
      const item = operation as { op?: string; path?: string; value?: unknown }
      const path = String(item.path || "")
      if (path === "/host" || path.startsWith("/host/")) {
        this.reportHostStateMutation()
        return
      }
      if (path === "/protocol") return
      if (path === "/agent") {
        if (item.op === "remove") nextState = {}
        if (item.op === "add" || item.op === "replace") nextState = normalizeAgentState(item.value)
        return
      }
      nextState = applyJsonPatch(nextState, [{
        ...item,
        path: path.startsWith("/agent/") ? path.slice(6) : path
      }])
    })
    this.agentState = normalizeAgentState(nextState)
    this.props.onAgentStateChange?.(this.agentState)
    this.scheduleSave()
  }

  private normalizeMessage(rawMessage: ChatMessage): ChatMessage {
    const result = { ...(rawMessage || {}) } as ChatMessage
    result.id = result.id || uuid()
    result.role = result.role === 'agent' ? 'assistant' : result.role || 'assistant'
    if (result.content === undefined || result.content === null) {
      result.content = ''
    }
    if (result.menuMention) {
      result.menuMention = this.resolveMenuMention(result.menuMention) || {
        ...clone(result.menuMention),
        valid: false
      }
    }
    if (result.streamingError && !result.streaming_error) {
      result.streaming_error = 'AG-UI run failed.'
    }
    if (result.references) {
      result.extra_data = {
        ...(result.extra_data || {}),
        references: result.extra_data?.references || normalizeReferenceGroups(result.references)
      }
    }
    if (result.extra_data?.references) {
      result.extra_data.references = normalizeReferenceGroups(result.extra_data.references)
    }
    if (result.role === 'assistant') {
      this.mergeMessageToolCalls(result)
    }
    return result
  }

  private normalizeStoredMessages(messages: ChatMessage[]): ChatMessage[] {
    const normalized: ChatMessage[] = []
    messages.forEach((rawMessage) => {
      const message = this.normalizeMessage(rawMessage)
      if (message.role === 'reasoning') {
        this.consumeReasoningMessage(message, normalized)
        return
      }
      normalized.push(message)
    })
    return normalized
  }

  private mergeIncomingMessages(messages: ChatMessage[]): void {
    const previousById: Record<string, ChatMessage> = {}
    this.messages.forEach((message) => {
      previousById[message.id] = message
    })
    const normalized: ChatMessage[] = []
    messages.forEach((rawMessage) => {
      let message = this.normalizeMessage(rawMessage)
      message = this.mergeMessageMetadata(message, previousById[message.id])
      if (message.role === 'reasoning') {
        this.consumeReasoningMessage(message, normalized)
        return
      }
      normalized.push(message)
    })
    this.messages = normalized
  }

  private mergeMessageMetadata(message: ChatMessage, previous?: ChatMessage): ChatMessage {
    if (!previous) {
      return message
    }
    if (previous.tool_calls?.length && !message.tool_calls?.length) {
      message.tool_calls = previous.tool_calls
    }
    if (previous.extra_data) {
      message.extra_data = {
        ...previous.extra_data,
        ...(message.extra_data || {})
      }
    }
    if (previous.streaming_error && !message.streaming_error) {
      message.streaming_error = previous.streaming_error
    }
    if (previous.menuMention && !message.menuMention) {
      message.menuMention = previous.menuMention
    }
    if (previous.recordSelection && !message.recordSelection) {
      message.recordSelection = previous.recordSelection
    }
    return message
  }

  private resolveMenuMention(mention: MenuMention): MenuMention | undefined {
    const option = (this.props.menuOptions || []).find((item) =>
      item.menuId === mention.menuId && item.actionId === mention.actionId
    )
    return option ? { ...clone(option), valid: true } : undefined
  }

  private isCurrentRecordSelection(selection: RecordSelection): boolean {
    const host = this.props.hostState
    return selection.snapshotId === host.snapshotId && selection.hostRevision === host.hostRevision &&
      Boolean(host.capabilities?.records.some((record) => record.token === selection.token))
  }

  private revalidateMenuMentions(): boolean {
    let changed = false
    this.messages.forEach((message) => {
      if (!message.menuMention) return
      const next = this.resolveMenuMention(message.menuMention) || {
        ...clone(message.menuMention),
        valid: false
      }
      if (JSON.stringify(next) !== JSON.stringify(message.menuMention)) {
        message.menuMention = next
        changed = true
      }
    })
    return changed
  }

  private consumeReasoningMessage(message: ChatMessage, targetMessages: ChatMessage[]): void {
    const steps = normalizeReasoningSteps(message.extra_data?.reasoning_steps, asText(message.content))
    const target = [...targetMessages].reverse().find((item) => item.role === 'assistant')
    if (!target) {
      message.extra_data = {
        ...(message.extra_data || {}),
        reasoning_steps: steps
      }
      targetMessages.push(message)
      return
    }
    target.extra_data = target.extra_data || {}
    target.extra_data.reasoning_steps = [...(target.extra_data.reasoning_steps || []), ...steps]
  }

  private mergeMessageToolCalls(message: ChatMessage): void {
    const calls = [
      ...(message.toolCalls || []).map((call) => toolCallFromTransport(call, message.id)),
      ...(message.tool_calls || []).map((call) => ({ ...call, message_id: message.id }))
    ].filter(Boolean) as ToolCall[]
    if (!calls.length) {
      return
    }
    message.tool_calls = []
    calls.forEach((call) => {
      const key = toolKey(call)
      const existing = this.toolsByKey[key]
      const normalized: ToolCall = {
        ...call,
        id: toolCallId(call) || undefined,
        tool_call_id: toolCallId(call) || undefined,
        name: toolName(call),
        tool_name: toolName(call),
        tool: toolName(call),
        args: toolArgs(call),
        tool_args: toolArgs(call),
        status: call.status || 'pending',
        key,
        message_id: message.id
      }
      this.toolsByKey[key] = existing ? { ...existing, ...normalized } : normalized
      message.tool_calls?.push(this.toolsByKey[key])
    })
  }

  private setTransportState(state: TransportState): void {
    this.transportState = state
    this.props.onTransportStateChange?.(state)
    this.emit()
  }

  private scheduleSave(): void {
    if (!this.session || !this.props.hostBridge?.saveSession) {
      return
    }
    if (this.saveTimer) {
      clearTimeout(this.saveTimer)
    }
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null
      void this.queueSave()
    }, 600)
  }

  private queueSave(): Promise<void> {
    this.saveQueue = this.saveQueue.then(() => this.saveSession(), () => this.saveSession())
    return this.saveQueue
  }

  private async saveSession(attempt = 0): Promise<void> {
    if (!this.session || !this.props.hostBridge?.saveSession) {
      return
    }
    const result = await this.props.hostBridge.saveSession(this.session.id, {
      name: this.session.name || 'New chat',
      surface: this.props.surface || this.session.surface || 'dock',
      messages: this.messages,
      agentState: normalizeAgentState(this.agentState),
      uiPreferences: this.session.uiPreferences || {},
      expectedSessionRevision: this.session.sessionRevision ?? 0
    })
    if (result && typeof result === 'object' && (result as { ok?: boolean }).ok === false) {
      const failure = result as { error?: string }
      if (failure.error === 'session_not_found' && attempt === 0 &&
          this.props.hostBridge.createSession) {
        const previous = this.session
        const replacement = sessionFromResult(await this.props.hostBridge.createSession({
          name: previous.name || 'New chat',
          surface: this.props.surface || previous.surface || 'dock',
          agent_id: previous.agent_id || this.props.agentId || false
        }))
        if (!replacement.id || replacement.protocol !== AGUI_ODOO_PROTOCOL) {
          throw new Error('无法创建替代会话。')
        }
        this.session = {
          ...replacement,
          messages: this.messages,
          agentState: normalizeAgentState(this.agentState),
          uiPreferences: previous.uiPreferences || replacement.uiPreferences || {}
        }
        this.threadId = replacement.thread_id
        this.props.onSessionChange?.(this.session)
        this.emit()
        return this.saveSession(1)
      }
      if (failure.error === 'session_revision_conflict' && attempt === 0 &&
          this.props.hostBridge.loadSession) {
        const remote = sessionFromResult(
          await this.props.hostBridge.loadSession(this.session.id)
        )
        this.messages = mergeMessagesById(remote.messages || [], this.messages)
        this.session = { ...this.session, ...remote, messages: this.messages }
        this.notifyMessages()
        return this.saveSession(1)
      }
      const error = new Error(
        failure.error === 'session_revision_conflict'
          ? '会话保存连续发生版本冲突，确认结果仍保留在当前页面。'
          : failure.error || 'Session save failed.'
      )
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      throw error
    }
    if (result) {
      this.session = {
        ...this.session,
        ...sessionFromResult(result)
      }
      this.props.onSessionChange?.(this.session)
      this.emit()
    }
  }

  private notifyMessages(): void {
    this.props.onMessagesChange?.(this.messages)
  }

  private emit(): void {
    this.listeners.forEach((listener) => listener())
  }
}
