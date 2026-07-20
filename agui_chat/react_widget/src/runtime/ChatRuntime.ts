import type {
  AguiChatProps,
  AttachmentRef,
  ChatMessage,
  HostBridgeToolCall,
  LoadedSession,
  MenuMention,
  MentionReference,
  RecordCandidate,
  RecordSelection,
  RelationCandidate,
  RuntimeSnapshot,
  SelectedAgentSkill,
  SessionEntry,
  ToolCall,
  TransportState,
  WorkspaceCapability,
  WorkspaceEntry,
  WorkspaceReference
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

const DEFAULT_SESSION_NAME = '新对话'
const MAX_SESSION_NAME_LENGTH = 30

type RunContext = {
  threadId: string
  controller: AbortController
  cancelled: boolean
  finalized: boolean
  savePromise: Promise<void> | null
  currentRunId: string
  agentRunId: string
  currentRequestId: string
  activeClientTools: Set<string>
  receivedTerminalEvent: boolean
  receivedRunStarted: boolean
  upstreamError: string
  pendingHostBridgePromises: Promise<unknown>[]
  hostBridgeFollowupNeeded: boolean
  branch?: {
    sourceSession: LoadedSession
    sourceCapability: WorkspaceCapability
    branchSessionId: string | number
    sourceThreadId: string
    sourceRunId: string
    targetMessageId: string
  }
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
        title: textSummary(step, 80) || '推理过程',
        content: step
      }
    }
    const raw = step && typeof step === 'object' ? (step as Record<string, unknown>) : {}
    const content = raw.content || raw.reasoning || raw.text || raw.action || ''
    return {
      title: String(raw.title || textSummary(content || raw, 80) || '推理过程'),
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

function normalizeSessionName(value: unknown): string {
  if (typeof value !== 'string') return ''
  const normalized = value.replace(/\s+/g, ' ').trim()
  const characters = Array.from(normalized)
  return characters.length > MAX_SESSION_NAME_LENGTH
    ? `${characters.slice(0, MAX_SESSION_NAME_LENGTH - 1).join('')}…`
    : normalized
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

  private workspaceCapability: WorkspaceCapability | null = null

  private serverConfirmationDecisions: Record<string, boolean> = {}

  constructor(props: AguiChatProps) {
    this.props = props
    const initialSession = props.session?.protocol === AGUI_ODOO_PROTOCOL ? props.session : null
    const storedAgentState = initialSession?.agentState || props.agentState || {}
    this.threadId = props.threadId || initialSession?.thread_id || uuid()
    this.agentState = normalizeAgentState(storedAgentState)
    this.messages = this.normalizeStoredMessages(props.initialMessages || initialSession?.messages || [])
    this.restoreCurrentRunId()
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
    const menuMentionsChanged = Boolean(nextProps.menuOptions && this.revalidateMenuMentions())
    const mentionsChanged = this.revalidateMentions()
    const skillsChanged = this.revalidateSkills()
    if (menuMentionsChanged || mentionsChanged || skillsChanged) {
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
    this.loadingSessions = true
    this.emit()
    try {
      if (await this.createSession()) await this.refreshSessions()
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
      this.error = ''
    } catch (reason) {
      this.reportError(reason, '加载会话失败。')
    } finally {
      this.loadingSessions = false
      this.emit()
    }
  }

  async refreshSessions(): Promise<boolean> {
    const bridge = this.props.hostBridge || {}
    if (!bridge.listSessions) {
      return true
    }
    this.loadingSessions = true
    this.emit()
    try {
      const result = await bridge.listSessions()
      this.sessions = sessionListFromResult(result)
      this.error = ''
      return true
    } catch (reason) {
      this.reportError(reason, '刷新会话列表失败。')
      return false
    } finally {
      this.loadingSessions = false
      this.emit()
    }
  }

  async archiveSession(sessionId: string | number): Promise<boolean> {
    if (this.running || !this.props.hostBridge?.archiveSession) return false
    try {
      const result = await Promise.resolve(this.props.hostBridge.archiveSession(sessionId))
      if (isRecord(result) && result.ok === false) {
        throw new Error(String(result.error || result.code || '归档失败。'))
      }
      this.sessions = this.sessions.filter((entry) => entry.id !== sessionId)
      if (this.session?.id === sessionId) {
        this.clearCurrentSession()
        this.loadingSessions = true
        this.emit()
        let created = false
        try {
          created = await this.createSession()
        } finally {
          this.loadingSessions = false
          this.emit()
        }
        if (!created) return false
      }
      await this.refreshSessions()
      return true
    } catch (reason) {
      const error = reason instanceof Error ? reason : new Error(String(reason))
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }
  }

  async send(
    content: string,
    attachments: AttachmentRef[] = [],
    selection?: MentionReference[] | MenuMention,
    recordSelection?: RecordSelection,
    skills: SelectedAgentSkill[] = [],
    workspaceReferences: WorkspaceReference[] = []
  ): Promise<boolean> {
    const text = content.trim()
    const mentions = Array.isArray(selection) ? selection.map((item) => clone(item)) : []
    const workspace = workspaceReferences.map((item) => clone(item))
    const menuMention = selection && !Array.isArray(selection)
      ? selection
      : !selection ? this.resolveTypedMenuMention(text) : undefined
    const currentMenu = menuMention ? this.resolveMenuMention(menuMention) : undefined
    if (menuMention && !currentMenu) {
      const error = new Error('所选菜单已失效或无权访问，请重新选择。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }
    const mentionError = this.validateMentions(mentions)
    if (mentionError) {
      const error = new Error(mentionError)
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }
    if (mentions.length + workspace.length > 5) {
      const error = new Error('HRP 引用与工作区引用合计最多 5 个。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }
    if (recordSelection && !this.isCurrentRecordSelection(recordSelection)) {
      const error = new Error('记录候选已过期，请重新筛选。')
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }
    const skillError = this.validateSkills(skills)
    if (skillError) {
      const error = new Error(skillError)
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }
    if ((!text && !attachments.length && !currentMenu && !mentions.length && !workspace.length && !recordSelection) || this.running || this.loadingSessions) {
      return false
    }
    try {
      endpoint(this.props)
    } catch (error) {
      this.error = (error as Error).message
      this.props.onError?.(error)
      this.emit()
      return false
    }
    if (!await this.ensureSession()) return false

    const messageId = uuid()
    let syncedAttachments: AttachmentRef[]
    try {
      await this.ensureWorkspaceCapability()
      syncedAttachments = await this.syncAttachments(messageId, attachments)
    } catch (reason) {
      const error = reason instanceof Error ? reason : new Error(String(reason))
      this.error = error.message
      this.props.onError?.(error)
      this.emit()
      return false
    }

    this.messages.push({
      id: messageId,
      role: 'user',
      content: text,
      attachments: clone(syncedAttachments),
      mentions: mentions.length ? mentions : undefined,
      workspaceReferences: workspace.length ? workspace : undefined,
      skills: skills.length ? skills.map((skill) => ({ ...skill, valid: true })) : undefined,
      menuMention: currentMenu,
      recordSelection: recordSelection ? clone(recordSelection) : undefined,
      created_at: Date.now()
    })
    this.nameSessionFromMessage(this.messages[this.messages.length - 1])
    await this.executeNewTurn()
    if (this.transportState === 'error') {
      return false
    }
    return true
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
    if (result.server_confirmation === true) {
      await this.confirmServerTool(current, approved)
      return
    }
    const authorizationId = String(result.authorization_id || tool.confirmation_id || '')
    if (
      !bridge?.confirmTool || !authorizationId || this.running ||
      current.status !== 'needs_confirmation' || this.confirmingHostBridgeTools[key]
    ) return
    const call: HostBridgeToolCall = {
      id: toolCallId(current) || false, tool: toolName(current),
      arguments: toolArgs(current), message_id: current.message_id || false,
      context: {
        requestId: this.currentRequestId,
        runId: this.currentRunId,
        threadId: this.threadId,
        selectedMentionTokens: this.latestMentionTokens()
      }
    }
    this.confirmingHostBridgeTools[key] = true
    const context = this.createRunContext(this.currentRunId)
    await this.executeRunLifecycle(context, async () => {
      const resultPromise = Promise.resolve()
        .then(() => bridge.confirmTool!(call, authorizationId, approved))
        .then(
          (value) => this.normalizeHostBridgeSuccess(current, value),
          (error): Record<string, unknown> => ({
            ok: false,
            operation: toolName(current),
            error: (error as Error)?.message || '工具确认失败。'
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

  private async confirmServerTool(tool: ToolCall, approved: boolean): Promise<void> {
    const key = toolKey(tool)
    if (this.running || this.serverConfirmationDecisions[key] !== undefined ||
        tool.status !== 'needs_confirmation') return
    this.serverConfirmationDecisions[key] = approved
    tool.status = 'running'
    tool.needs_confirmation = false
    this.notifyMessages()
    this.emit()

    const paused = Object.values(this.toolsByKey).filter((candidate) =>
      isRecord(candidate.result) && candidate.result.server_confirmation === true
    )
    if (!paused.length || paused.some((candidate) =>
      this.serverConfirmationDecisions[toolKey(candidate)] === undefined
    )) return

    paused.forEach((candidate) => {
      const accepted = this.serverConfirmationDecisions[toolKey(candidate)]
      const id = toolCallId(candidate)
      const content = accepted
        ? { accepted: true }
        : { accepted: false, note: '用户拒绝执行此工具。' }
      this.messages.push({
        id: `tool-server-${id || uuid()}`,
        role: 'tool',
        name: toolName(candidate),
        toolCallId: id,
        tool_call_id: id,
        content: JSON.stringify(content),
        hidden: true,
        created_at: Date.now()
      })
      if (!accepted) {
        candidate.status = 'error'
        candidate.error = '用户拒绝执行此工具。'
      }
      candidate.result = {
        ...(isRecord(candidate.result) ? candidate.result : {}),
        server_confirmation: false,
        accepted
      }
    })
    this.pendingAssistantId = uuid()
    this.messages.push({
      id: this.pendingAssistantId,
      role: 'assistant',
      content: '',
      tool_calls: [],
      created_at: Date.now()
    })
    const context = this.createRunContext(this.currentRunId)
    await this.executeRunLifecycle(context, () => this.run(context, 0))
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
      rowToken: typeof result.rowToken === 'string' ? result.rowToken : false,
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

  removeMention(messageId: string, referenceId: string): void {
    if (this.running) return
    const message = this.messages.find((item) => item.id === messageId && item.role === 'user')
    if (!message?.mentions?.some((mention) => mention.id === referenceId)) return
    message.mentions = message.mentions.filter((mention) => mention.id !== referenceId)
    if (!message.mentions.length) delete message.mentions
    this.notifyMessages()
    this.scheduleSave()
    this.emit()
  }

  async regenerate(messageId: string): Promise<void> {
    if (this.running || !this.session || !this.props.hostBridge?.forkSession) return
    const target = this.messages.find((message) => message.id === messageId)
    const sourceRunId = String(target?.extra_data?.agent_run_id || '')
    if (!target || !this.isRegenerationTarget(target) || !sourceRunId) return

    let sourceSession: LoadedSession | null = null
    let branchSession: LoadedSession | null = null
    try {
      await this.queueSave()
      if (!this.session) throw new Error('当前聊天会话不可用。')
      const sourceCapability = await this.ensureWorkspaceCapability(true)
      if (!sourceCapability) throw new Error('分支会话授权不可用。')
      sourceSession = {
        ...clone(this.session),
        messages: clone(this.messages),
        agentState: clone(this.agentState)
      }
      const result = await this.props.hostBridge.forkSession(this.session.id, {
        targetMessageId: target.id,
        sourceRunId,
        expectedSessionRevision: this.session.sessionRevision ?? 0
      })
      if (isRecord(result) && result.ok === false) {
        const messages: Record<string, string> = {
          session_revision_conflict: '会话已在其他页面更新，请刷新后重试。',
          branch_target_not_found: '该回答缺少可用的运行记录，无法创建分支。',
          branch_target_not_final: '该回答仍有待处理工具，无法创建分支。'
        }
        throw new Error(messages[String(result.error)] || '创建分支会话失败。')
      }
      branchSession = sessionFromResult(result)
      const metadata: Record<string, unknown> =
        isRecord(result) && isRecord(result.branch) ? result.branch : {}
      if (
        !branchSession.id || branchSession.protocol !== AGUI_ODOO_PROTOCOL ||
        metadata.sourceThreadId !== sourceSession.thread_id ||
        metadata.sourceRunId !== sourceRunId || metadata.targetMessageId !== target.id
      ) {
        throw new Error('分支会话元数据无效。')
      }
      this.applyLoadedSession(branchSession)
      this.pendingAssistantId = uuid()
      this.messages.push({
        id: this.pendingAssistantId,
        role: 'assistant',
        content: '',
        tool_calls: [],
        created_at: Date.now()
      })
      const context = this.createRunContext()
      context.branch = {
        sourceSession,
        sourceCapability,
        branchSessionId: branchSession.id,
        sourceThreadId: sourceSession.thread_id,
        sourceRunId,
        targetMessageId: target.id
      }
      await this.executeRunLifecycle(context, () => this.run(context, 0))
      await this.refreshSessions()
    } catch (reason) {
      if (branchSession?.id) {
        try {
          await Promise.resolve(this.props.hostBridge.archiveSession?.(branchSession.id))
        } catch (_archiveError) {
          // The server cleanup queue remains the authority for an already archived branch.
        }
      }
      if (sourceSession) this.applyLoadedSession(sourceSession)
      this.reportError(reason, '重新生成回答失败。')
    }
  }

  async uploadAttachment(file: File, onProgress?: (progress: number) => void): Promise<AttachmentRef> {
    await this.ensureSession()
    if (!this.session) {
      throw new Error('上传附件前需要先创建聊天会话。')
    }
    const sessionId = String(this.session.id || '')
    if (!/^\d+$/.test(sessionId)) {
      throw new Error('当前聊天会话不可用。')
    }
    const csrfToken = this.attachmentCsrfToken()
    return new Promise((resolve, reject) => {
      const form = new FormData()
      form.append('chat_session_id', sessionId)
      form.append('file', file)
      form.append('csrf_token', csrfToken)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/agui_chat/attachment/upload')
      xhr.withCredentials = true
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress?.(Math.round((event.loaded / event.total) * 100))
        }
      }
      xhr.onerror = () => reject(new Error('附件上传失败。'))
      xhr.onload = () => {
        let payload: { attachment?: AttachmentRef; error?: string } = {}
        try {
          payload = JSON.parse(xhr.responseText || '{}')
        } catch (_error) {
          reject(new Error('附件上传响应无效。'))
          return
        }
        if (xhr.status < 200 || xhr.status >= 300 || !payload.attachment) {
          reject(new Error(payload.error || '附件上传失败。'))
          return
        }
        onProgress?.(100)
        resolve(payload.attachment)
      }
      xhr.send(form)
    })
  }

  async deleteAttachment(attachmentId: string): Promise<void> {
    const body = new URLSearchParams({
      attachment_id: attachmentId,
      csrf_token: this.attachmentCsrfToken()
    })
    const response = await fetch('/agui_chat/attachment/delete', {
      method: 'POST',
      credentials: this.props.credentials || 'same-origin',
      body
    })
    if (!response.ok) {
      throw new Error('附件删除失败。')
    }
  }

  private attachmentCsrfToken(): string {
    const token = String(this.props.csrfToken || '').trim()
    if (!token) {
      throw new Error('附件请求缺少 CSRF 令牌。')
    }
    return token
  }

  async listWorkspace(path = ''): Promise<WorkspaceEntry[]> {
    const capability = await this.ensureWorkspaceCapability(true)
    if (!capability) throw new Error('工作区 capability 不可用。')
    const query = new URLSearchParams({ threadId: this.threadId, path })
    const response = await fetch(`${this.workspaceEndpoint('/workspace/files')}?${query}`, {
      credentials: this.runtimeCredentials(),
      headers: this.workspaceHeaders(capability)
    })
    const payload = await this.workspaceJson(response)
    return Array.isArray(payload.entries) ? payload.entries as WorkspaceEntry[] : []
  }

  async readWorkspaceFile(path: string): Promise<{ blob: Blob; mimeType: string }> {
    const capability = await this.ensureWorkspaceCapability(true)
    if (!capability) throw new Error('工作区 capability 不可用。')
    const query = new URLSearchParams({ threadId: this.threadId, path })
    const response = await fetch(`${this.workspaceEndpoint('/workspace/file')}?${query}`, {
      credentials: this.runtimeCredentials(),
      headers: this.workspaceHeaders(capability)
    })
    if (!response.ok) throw new Error(await this.workspaceError(response))
    return {
      blob: await response.blob(),
      mimeType: response.headers.get('content-type') || 'application/octet-stream'
    }
  }

  async downloadWorkspaceFile(path: string): Promise<void> {
    const capability = await this.ensureWorkspaceCapability(true)
    if (!capability) throw new Error('工作区 capability 不可用。')
    const query = new URLSearchParams({ threadId: this.threadId, path, download: 'true' })
    const response = await fetch(`${this.workspaceEndpoint('/workspace/file')}?${query}`, {
      credentials: this.runtimeCredentials(),
      headers: this.workspaceHeaders(capability)
    })
    if (!response.ok) throw new Error(await this.workspaceError(response))
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = path.split('/').pop() || 'download'
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  async deleteWorkspaceEntry(path: string, recursive = false): Promise<void> {
    const capability = await this.ensureWorkspaceCapability(true)
    if (!capability) throw new Error('工作区 capability 不可用。')
    const response = await fetch(this.workspaceEndpoint('/workspace/file'), {
      method: 'DELETE',
      credentials: this.runtimeCredentials(),
      headers: {
        ...this.workspaceHeaders(capability),
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ threadId: this.threadId, path, recursive })
    })
    if (!response.ok) throw new Error(await this.workspaceError(response))
  }

  private runtimeCredentials(): RequestCredentials {
    return this.props.credentials || (this.props.allowCrossOriginDev ? 'include' : 'same-origin')
  }

  private workspaceEndpoint(path: string): string {
    const runtime = endpoint(this.props)
    return `${runtime.slice(0, -'/agui'.length)}${path}`
  }

  private workspaceHeaders(capability: WorkspaceCapability): Record<string, string> {
    return {
      'X-AGUI-Capability': capability.capability,
      'X-AGUI-Thread': this.threadId
    }
  }

  private async workspaceError(response: Response): Promise<string> {
    try {
      const payload = await response.clone().json() as { detail?: string; error?: string }
      return payload.detail || payload.error || `工作区请求失败（HTTP ${response.status}）。`
    } catch (_error) {
      return `工作区请求失败（HTTP ${response.status}）。`
    }
  }

  private async workspaceJson(response: Response): Promise<Record<string, unknown>> {
    if (!response.ok) throw new Error(await this.workspaceError(response))
    return response.json() as Promise<Record<string, unknown>>
  }

  private async ensureWorkspaceCapability(required = false): Promise<WorkspaceCapability | null> {
    const current = this.workspaceCapability
    if (current && current.threadId === this.threadId && current.expiresAt > Date.now() / 1000 + 30) {
      return current
    }
    const bridge = this.props.hostBridge
    if (!bridge?.getWorkspaceCapability) {
      if (required) throw new Error('HRP 未提供工作区 capability。')
      return null
    }
    if (!this.session?.id) throw new Error('当前聊天会话不可用。')
    const result = await Promise.resolve(bridge.getWorkspaceCapability(this.session.id))
    if (
      result?.ok === false || !result.capability || !result.threadId ||
      typeof result.expiresAt !== 'number' || result.threadId !== this.threadId
    ) {
      throw new Error(result?.error || result?.code || '工作区 capability 获取失败。')
    }
    this.workspaceCapability = {
      capability: result.capability,
      threadId: result.threadId,
      expiresAt: result.expiresAt
    }
    return this.workspaceCapability
  }

  private safeAttachmentName(name: string, index: number): string {
    const basename = name.replace(/\\/g, '/').split('/').pop() || `attachment-${index + 1}`
    const safe = basename.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^\.+/, '').slice(0, 120)
    return `${index + 1}-${safe || `attachment-${index + 1}`}`
  }

  private async syncAttachments(
    messageId: string,
    attachments: AttachmentRef[]
  ): Promise<AttachmentRef[]> {
    if (!attachments.length) return []
    if (!this.props.hostBridge?.getWorkspaceCapability) return clone(attachments)
    const capability = await this.ensureWorkspaceCapability(true)
    if (!capability) throw new Error('工作区 capability 不可用。')
    const synced: AttachmentRef[] = []
    try {
      for (let index = 0; index < attachments.length; index += 1) {
        const attachment = attachments[index]
        const source = await fetch(`/agui_chat/attachment/${encodeURIComponent(attachment.id)}`, {
          credentials: this.props.credentials || 'same-origin'
        })
        if (!source.ok) throw new Error(`附件 ${attachment.name} 读取失败。`)
        const blob = await source.blob()
        const path = `attachments/${messageId}/${this.safeAttachmentName(attachment.name, index)}`
        const form = new FormData()
        form.set('threadId', this.threadId)
        form.set('path', path)
        form.set('file', blob, attachment.name)
        const response = await fetch(this.workspaceEndpoint('/workspace/upload'), {
          method: 'POST',
          credentials: this.runtimeCredentials(),
          headers: this.workspaceHeaders(capability),
          body: form
        })
        if (!response.ok) throw new Error(await this.workspaceError(response))
        synced.push({ ...clone(attachment), workspacePath: path })
      }
      return synced
    } catch (error) {
      await Promise.all(synced.map((attachment) => this.deleteWorkspaceEntry(
        attachment.workspacePath || ''
      ).catch(() => undefined)))
      throw error
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
    const type = eventType(event)
    if (type === 'CUSTOM' && event.name === 'AGUI_BRANCH_PREPARED') {
      this.props.onEvent?.(event)
      this.applyBranchPrepared(event.value, context)
      this.notifyMessages()
      this.emit()
      return
    }
    const eventRunId = String(event.runId || event.run_id || "")
    const eventThreadId = String(event.threadId || event.thread_id || "")
    const expectedRunId = context?.currentRunId || this.currentRunId
    const expectedThreadId = context?.threadId || this.threadId
    if ((eventRunId && eventRunId !== expectedRunId) ||
        (eventThreadId && eventThreadId !== expectedThreadId)) {
      return
    }
    const data = eventData(event)
    let tool: ToolCall | null
    this.props.onEvent?.(event)

    if (type === 'RUN_STARTED') {
      if (context) {
        context.receivedRunStarted = true
        if (eventRunId) {
          context.currentRunId = eventRunId
          context.agentRunId = eventRunId
          this.currentRunId = eventRunId
        }
      }
      this.assignAgentRunId(this.ensureAssistant(), eventRunId || context?.currentRunId || '')
    } else if (type === 'TEXT_MESSAGE_START') {
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
      const message = String(data.message || data.content || event.message || 'AG-UI 运行失败。')
      if (context) {
        context.upstreamError = message
        context.receivedTerminalEvent = true
      }
      this.recordRunError(message)
    } else if (type === 'RUN_FINISHED') {
      if (context) context.receivedTerminalEvent = true
      this.applyRunFinished(event, context)
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

  private applyBranchPrepared(value: unknown, context: RunContext | null): void {
    if (!context?.branch || !isRecord(value)) return
    const targetThreadId = String(value.targetThreadId || '')
    const sourceThreadId = String(value.sourceThreadId || '')
    const generatedRunId = String(value.runId || '')
    const rawMap = isRecord(value.runIdMap) ? value.runIdMap : {}
    if (
      targetThreadId !== context.threadId ||
      sourceThreadId !== context.branch.sourceThreadId ||
      value.targetMessageId !== context.branch.targetMessageId ||
      !generatedRunId
    ) return
    const runIdMap: Record<string, string> = {}
    Object.entries(rawMap).forEach(([source, target]) => {
      if (source && typeof target === 'string' && target) runIdMap[source] = target
    })
    this.messages.forEach((message) => {
      const oldRunId = String(message.extra_data?.agent_run_id || '')
      if (oldRunId && runIdMap[oldRunId]) {
        this.assignAgentRunId(message, runIdMap[oldRunId])
      }
    })
    context.currentRunId = generatedRunId
    context.agentRunId = generatedRunId
    this.currentRunId = generatedRunId
  }

  private async initSessions(): Promise<void> {
    if (this.session || !this.props.hostBridge?.listSessions) {
      return
    }
    try {
      if (!await this.refreshSessions()) return
      if (this.sessions.length && this.props.hostBridge?.loadSession) {
        await this.loadSession(this.sessions[0].id)
      } else if (!this.sessions.length && this.props.hostBridge?.createSession) {
        await this.newSession()
      }
    } catch (error) {
      this.props.onError?.(error)
    }
  }

  private async createSession(): Promise<boolean> {
    const bridge = this.props.hostBridge || {}
    if (!bridge.createSession) {
      this.clearCurrentSession()
      return true
    }
    try {
      const result = await bridge.createSession({
        surface: this.props.surface || 'dock',
        agent_id: this.props.agentId || false
      })
      this.applyLoadedSession(sessionFromResult(result))
      this.error = ''
      return true
    } catch (reason) {
      this.reportError(reason, '创建会话失败。')
      return false
    }
  }

  private async ensureSession(): Promise<boolean> {
    if (this.session || !this.props.hostBridge?.createSession) {
      return true
    }
    await this.newSession()
    return Boolean(this.session)
  }

  private applyLoadedSession(session: LoadedSession): void {
    if (session.protocol !== AGUI_ODOO_PROTOCOL) {
      throw new Error('不支持此聊天会话协议。')
    }
    this.session = session
    this.threadId = session.thread_id || this.props.threadId || uuid()
    this.workspaceCapability = null
    const storedAgentState = session.agentState || this.props.agentState || {}
    this.agentState = normalizeAgentState(storedAgentState)
    this.messages = this.normalizeStoredMessages(session.messages || [])
    this.restoreCurrentRunId()
    this.currentRequestId = ''
    this.toolsByKey = {}
    this.pendingAssistantId = null
    this.activeTextMessageId = null
    this.activeToolCallId = null
    this.executedHostBridgeTools = {}
    this.confirmingHostBridgeTools = {}
    this.resumedToolResults = {}
    this.serverConfirmationDecisions = {}
    this.undoInFlight = {}
    this.props.onSessionChange?.(session)
    this.notifyMessages()
    this.props.onAgentStateChange?.(this.agentState)
    if (needsAgentStateCleanup(storedAgentState)) {
      this.scheduleSave()
    }
  }

  private clearCurrentSession(): void {
    if (this.saveTimer) {
      clearTimeout(this.saveTimer)
      this.saveTimer = null
    }
    this.session = null
    this.resetThread(uuid(), [])
    this.props.onSessionChange?.(null)
    this.emit()
  }

  private resetThread(threadId: string, messages: ChatMessage[]): void {
    this.cancel()
    this.threadId = threadId
    this.workspaceCapability = null
    this.currentRunId = ''
    this.currentRequestId = ''
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
    this.serverConfirmationDecisions = {}
    this.undoInFlight = {}
    this.notifyMessages()
  }

  private restoreCurrentRunId(): void {
    this.currentRunId = ''
    for (let index = this.messages.length - 1; index >= 0; index -= 1) {
      const runId = this.messages[index].extra_data?.agent_run_id
      if (typeof runId === 'string' && runId) {
        this.currentRunId = runId
        return
      }
    }
  }

  private async executeNewTurn(): Promise<void> {
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
    this.serverConfirmationDecisions = {}
    this.undoInFlight = {}
    const context = this.createRunContext()
    await this.executeRunLifecycle(context, () => this.run(context, 0))
  }

  private nameSessionFromMessage(message: ChatMessage): void {
    if (!this.session) return
    const currentName = this.session.name || ''
    if (currentName.trim() && currentName !== DEFAULT_SESSION_NAME) return

    const firstMentionLabel = message.mentions
      ?.map((mention) => normalizeSessionName(mention.label))
      .find(Boolean)
    const firstWorkspaceName = message.workspaceReferences
      ?.map((reference) => normalizeSessionName(reference.name))
      .find(Boolean)
    const firstAttachmentName = message.attachments
      ?.map((attachment) => normalizeSessionName(attachment.name))
      .find(Boolean)
    const name = [
      message.content,
      message.menuMention?.fullPath,
      message.recordSelection?.displayName,
      firstMentionLabel,
      firstWorkspaceName,
      firstAttachmentName
    ].map(normalizeSessionName).find(Boolean)
    if (!name) return

    this.session = { ...this.session, name }
    this.sessions = this.sessions.map((entry) =>
      entry.id === this.session?.id ? { ...entry, name } : entry
    )
    this.props.onSessionChange?.(this.session)
  }

  private createRunContext(agentRunId = uuid()): RunContext {
    const context: RunContext = {
      threadId: this.threadId,
      controller: new AbortController(),
      cancelled: false,
      finalized: false,
      savePromise: null,
      currentRunId: agentRunId,
      agentRunId,
      currentRequestId: '',
      activeClientTools: new Set(),
      receivedTerminalEvent: false,
      receivedRunStarted: false,
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
      if (context.branch && !context.receivedRunStarted) {
        await this.recoverBranchPreparation(context, error)
      } else {
        this.handleRunFailure(context, error)
      }
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
    this.error = context.upstreamError || (error as Error)?.message || 'AG-UI 运行失败。'
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

  private async recoverBranchPreparation(context: RunContext, error: unknown): Promise<void> {
    const branch = context.branch
    if (!branch || this.activeRunContext !== context) return
    try {
      await Promise.resolve(this.props.hostBridge?.archiveSession?.(branch.branchSessionId))
    } catch (_archiveError) {
      // AgentOS also removes partially prepared branch state before RUN_STARTED.
    }
    this.applyLoadedSession(branch.sourceSession)
    const failure = error instanceof Error ? error : new Error(String(error || '分支准备失败。'))
    this.error = failure.message
    this.transportState = 'error'
    try {
      this.props.onTransportStateChange?.('error')
      this.props.onError?.(failure)
    } catch (_callbackError) {
      // Recovery state must remain authoritative when a consumer callback fails.
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
    const capability = await this.ensureWorkspaceCapability()
    context.pendingHostBridgePromises = []
    context.hostBridgeFollowupNeeded = false
    const input = buildRunInput(
      this.messages, this.props, context.threadId, this.pendingAssistantId, this.agentState, {
        runId: context.agentRunId,
        branch: context.branch && !context.receivedRunStarted ? {
          sourceThreadId: context.branch.sourceThreadId,
          sourceRunId: context.branch.sourceRunId,
          targetMessageId: context.branch.targetMessageId
        } : undefined
      }
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
        ...(this.props.headers || {}),
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        'X-Request-ID': input.requestId,
        ...(capability ? this.workspaceHeaders(capability) : {}),
        ...(context.branch && !context.receivedRunStarted ? {
          'X-AGUI-Source-Capability': context.branch.sourceCapability.capability
        } : {})
      },
      body: JSON.stringify(input),
      signal: context.controller.signal
    })
    if (!response.ok) {
      throw transportError(response.status)
    }
    if (!(response.headers.get("content-type") || "").includes("text/event-stream")) {
      throw new Error("AG-UI 运行服务必须返回 text/event-stream。")
    }
    if (!response.body) {
      throw new Error("AG-UI SSE 响应没有正文。")
    }
    this.setTransportState("streaming")
    await this.readSse(response.body, context)
    this.throwIfRunCancelled(context)
    if (!context.receivedTerminalEvent) {
      throw new Error("AG-UI 数据流在 RUN_FINISHED 事件之前结束。")
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
          throw new Error('SSE 事件超过配置的大小限制。')
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
      this.props.onError?.(new Error('已忽略格式错误的 SSE 事件。'))
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
    this.assignAgentRunId(message, this.activeRunContext?.currentRunId || '')
    return message
  }

  private assignAgentRunId(message: ChatMessage, runId: string): void {
    if (!runId || (message.role !== 'assistant' && message.role !== 'agent')) return
    this.messages.forEach((candidate) => {
      if (
        candidate !== message &&
        (candidate.role === 'assistant' || candidate.role === 'agent') &&
        candidate.extra_data?.agent_run_id === runId
      ) {
        candidate.extra_data = { ...candidate.extra_data, agent_run_final: false }
      }
    })
    message.extra_data = {
      ...(message.extra_data || {}), agent_run_id: runId, agent_run_final: true
    }
  }

  private isRegenerationTarget(message: ChatMessage): boolean {
    if (
      (message.role !== 'assistant' && message.role !== 'agent') ||
      !message.content || message.streaming_error ||
      typeof message.extra_data?.agent_run_id !== 'string' ||
      !message.extra_data.agent_run_id
    ) return false
    const runId = message.extra_data.agent_run_id
    const index = this.messages.indexOf(message)
    const laterSameRun = index >= 0 && this.messages.slice(index + 1).some((candidate) =>
      (candidate.role === 'assistant' || candidate.role === 'agent') &&
      candidate.extra_data?.agent_run_id === runId
    )
    return !laterSameRun && !(message.tool_calls || []).some((tool) =>
      ['pending', 'running', 'needs_confirmation'].includes(tool.status || 'pending')
    )
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
    this.ensureAssistant().streaming_error = message || 'AG-UI 运行失败。'
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
          error: (error as Error)?.message || String(error || '宿主桥接调用失败。')
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
        threadId: context.threadId,
        selectedMentionTokens: this.latestMentionTokens()
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
        ? error : new Error(String(error || '会话保存失败。'))
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

  private applyRunFinished(event: Record<string, unknown>, context: RunContext | null): void {
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
        result: { ...value, server_confirmation: true }
      })
    })
    if (!context) return
    Object.values(this.toolsByKey).forEach((candidate) => {
      if (context.activeClientTools.has(toolName(candidate)) || candidate.result !== undefined ||
          !['pending', 'running'].includes(candidate.status || 'pending')) return
      this.mergeTool({
        id: toolCallId(candidate),
        name: toolName(candidate),
        status: 'needs_confirmation',
        needs_confirmation: true,
        result: {
          server_confirmation: true,
          operation: toolName(candidate),
          arguments: toolArgs(candidate)
        }
      })
    })
  }

  private appendReasoning(content: string): void {
    const message = this.ensureAssistant()
    message.extra_data = message.extra_data || {}
    message.extra_data.reasoning_steps = message.extra_data.reasoning_steps || []
    message.extra_data.reasoning_steps.push({
      title: '推理过程',
      content
    })
  }

  private reportHostStateMutation(): void {
    this.props.onError?.(new Error("已忽略智能体修改 HRP 宿主状态的尝试。"))
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
    if (Array.isArray(result.mentions)) {
      result.mentions = result.mentions.map((mention) => ({
        ...clone(mention),
        valid: this.isMentionCurrent(mention)
      }))
    }
    if (Array.isArray(result.skills)) {
      result.skills = result.skills.map((skill) => ({
        ...clone(skill),
        valid: this.isSkillCurrent(skill)
      }))
    }
    if (result.streamingError && !result.streaming_error) {
      result.streaming_error = 'AG-UI 运行失败。'
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
    if (previous.mentions?.length && !message.mentions?.length) {
      message.mentions = previous.mentions
    }
    if (previous.workspaceReferences?.length && !message.workspaceReferences?.length) {
      message.workspaceReferences = previous.workspaceReferences
    }
    if (previous.skills?.length && !message.skills?.length) {
      message.skills = previous.skills
    }
    if (previous.recordSelection && !message.recordSelection) {
      message.recordSelection = previous.recordSelection
    }
    return message
  }

  private isMentionCurrent(mention: MentionReference): boolean {
    if (!mention?.token || !mention.resourceKey || !mention.kind || !mention.action) return false
    const normalized = String(mention.expiresAt || '').includes('T')
      ? String(mention.expiresAt)
      : `${String(mention.expiresAt || '').replace(' ', 'T')}Z`
    const expires = Date.parse(normalized)
    return mention.valid !== false && Number.isFinite(expires) && expires > Date.now()
  }

  private latestMentionTokens(): string[] {
    const message = [...this.messages].reverse().find((item) => item.role === 'user')
    return (message?.mentions || []).filter((mention) => mention.valid).map((mention) => mention.token)
  }

  private validateMentions(mentions: MentionReference[]): string | null {
    if (mentions.length > 5) return '每条消息最多引用 5 个对象。'
    if (new Set(mentions.map((mention) => mention.resourceKey)).size !== mentions.length) {
      return '不能重复引用同一对象。'
    }
    const pageActions = mentions.filter((mention) => mention.pageAction ||
      ['open', 'create', 'view', 'edit', 'apply'].includes(mention.action))
    if (pageActions.length > 1) return '每条消息最多包含 1 个页面动作。'
    if (mentions.some((mention) => !this.isMentionCurrent(mention))) {
      return '对象引用已过期，请重新选择。'
    }
    return null
  }

  private revalidateMentions(): boolean {
    let changed = false
    this.messages.forEach((message) => {
      if (!message.mentions?.length) return
      message.mentions = message.mentions.map((mention) => {
        const valid = this.isMentionCurrent(mention)
        if (valid === mention.valid) return mention
        changed = true
        return { ...mention, valid }
      })
    })
    return changed
  }

  private isSkillCurrent(skill: SelectedAgentSkill): boolean {
    return Boolean((this.props.agentSkills || []).some((option) =>
      option.id === skill.id && option.name === skill.name
    ))
  }

  private validateSkills(skills: SelectedAgentSkill[]): string | null {
    if (skills.length > 1) return '每条消息只能选择 1 个技能。'
    if (new Set(skills.map((skill) => skill.id)).size !== skills.length) {
      return '不能重复选择同一技能。'
    }
    if (skills.some((skill) => !this.isSkillCurrent(skill))) {
      return '所选技能已不可用，请移除后重试。'
    }
    return null
  }

  private revalidateSkills(): boolean {
    let changed = false
    this.messages.forEach((message) => {
      if (!message.skills?.length) return
      message.skills = message.skills.map((skill) => {
        const valid = this.isSkillCurrent(skill)
        if (valid === skill.valid) return skill
        changed = true
        return { ...skill, valid }
      })
    })
    return changed
  }

  private resolveMenuMention(mention: MenuMention): MenuMention | undefined {
    const option = (this.props.menuOptions || []).find((item) =>
      item.menuId === mention.menuId && item.actionId === mention.actionId
    )
    return option ? { ...clone(option), valid: true } : undefined
  }

  private resolveTypedMenuMention(content: string): MenuMention | undefined {
    const normalize = (value: string) => value.trim().replace(/\s*\/\s*/g, ' / ').replace(/\s+/g, ' ')
    const text = normalize(content)
    const candidates = [text]
    const openMatch = text.match(/^(?:请)?(?:打开|进入|导航到|跳转到)\s*(.+?)(?:\s*菜单)?[。！？!?]?$/)
    if (openMatch?.[1]) candidates.unshift(normalize(openMatch[1]))

    const options = this.props.menuOptions || []
    for (const candidate of candidates) {
      const fullPath = options.filter((option) => normalize(option.fullPath) === candidate)
      if (fullPath.length === 1) return { ...clone(fullPath[0]), valid: true }
      const leaf = options.filter((option) => normalize(option.name) === candidate)
      if (leaf.length === 1) return { ...clone(leaf[0]), valid: true }
    }
    return undefined
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
      void this.persistImmediately()
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
      name: this.session.name || DEFAULT_SESSION_NAME,
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
          name: previous.name || DEFAULT_SESSION_NAME,
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
          : failure.error || '会话保存失败。'
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

  private reportError(reason: unknown, fallback: string): void {
    const error = reason instanceof Error && reason.message
      ? reason : new Error(String(reason || fallback))
    this.error = error.message || fallback
    try {
      this.props.onError?.(error)
    } catch (_callbackError) {
      // Runtime state remains usable even when an error callback fails.
    }
    this.emit()
  }

  private emit(): void {
    this.listeners.forEach((listener) => listener())
  }
}
