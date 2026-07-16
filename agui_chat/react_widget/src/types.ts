import type React from 'react'

export const AGUI_ODOO_PROTOCOL = 'agui.odoo.v2' as const

export type ChatSurface = 'dock' | 'standalone'

export type TransportState =
  | 'connecting'
  | 'streaming'
  | 'completed'
  | 'cancelled'
  | 'error'

export type ChatRole =
  | 'user'
  | 'assistant'
  | 'agent'
  | 'tool'
  | 'system'
  | 'developer'
  | 'reasoning'
  | 'activity'

export type ToolStatus =
  | 'pending'
  | 'running'
  | 'needs_confirmation'
  | 'ok'
  | 'error'
  | 'cancelled'

export interface OdooViewField {
  name: string
  string: string
  type: string
  relation: string | false
  selection: unknown
  readonly: boolean
  required: boolean
  invisible: boolean
  redacted: boolean
}

export interface MenuMentionOption {
  menuId: number
  actionId: number
  name: string
  path: string[]
  fullPath: string
}

export interface MenuMention extends MenuMentionOption {
  valid: boolean
}

export interface RecordCandidate {
  token: string
  displayName: string
}

export interface RecordSelection extends RecordCandidate {
  snapshotId: string
  hostRevision: number
}

export interface FilterFieldCapability {
  name: string
  string: string
  type: string
  relation: string | false
  selection: unknown
  operators: string[]
}

export interface ViewControlCapability {
  token: string
  type: 'open' | 'edit' | 'action' | 'object'
  label: string
  recordLabel: string
}

export interface ViewCapabilities {
  create: boolean
  open: boolean
  edit: boolean
  filter: boolean
  totalCount: number
  filterFields: Record<string, FilterFieldCapability>
  records: RecordCandidate[]
  controls: ViewControlCapability[]
}

export interface OdooHostSnapshot {
  protocol: typeof AGUI_ODOO_PROTOCOL
  snapshotId: string
  hostRevision: number
  capturedAt: string
  interactive: boolean
  surface: ChatSurface
  controller: {
    actionId: string | number | false
    controllerId: string
    dataPointId: string | false
    viewType: 'form' | 'list' | 'kanban' | false
    mode: string | false
  }
  action: Record<string, unknown> | false
  menu: Record<string, unknown> | false
  record: {
    model: string
    resId: number | false
    values: Record<string, unknown>
    dirty: Record<string, unknown>
    dirtyFields: string[]
  } | false
  selection: {
    model: string
    ids: number[]
    domain: unknown[]
    context: Record<string, unknown>
  } | false
  fields: Record<string, OdooViewField>
  capabilities: ViewCapabilities
}

export interface AguiClientTool {
  name: string
  description?: string
  parameters: Record<string, unknown>
}

export interface ProtocolHandshake {
  protocol: typeof AGUI_ODOO_PROTOCOL
  moduleVersion: string
  bundleVersion: string
  agentProtocol: typeof AGUI_ODOO_PROTOCOL
  agentBundleVersion: string
  commandCatalogHash: string
  agentCommandCatalogHash: string
}

export interface ReferenceItem {
  name: string
  url?: string
  content?: string
  meta_data?: Record<string, unknown>
}

export interface ReferenceGroup {
  query?: string
  references: ReferenceItem[]
}

export interface ReasoningStep {
  title: string
  content?: string
  action?: string
  result?: string
  reasoning?: string
}

export interface ToolCall {
  id?: string
  key?: string
  name?: string
  tool?: string
  tool_name?: string
  toolCallId?: string
  tool_call_id?: string
  args?: unknown
  tool_args?: unknown
  argsText?: string
  result?: unknown
  status?: ToolStatus
  error?: string | boolean
  createdAt?: string | number
  created_at?: string | number
  parentMessageId?: string
  message_id?: string
  needs_confirmation?: boolean
  confirmation_id?: string | false
}

export interface RelationCandidate {
  id: number
  displayName: string
  selected: boolean
}

export interface RelationSearchResult {
  ok: boolean
  operation: 'odoo.search_relation'
  field: string
  fieldLabel?: string
  fieldType: 'many2one' | 'many2many'
  relation: string
  query: string
  relationOperation: 'set' | 'link' | 'unlink'
  resolution: 'none' | 'unique_exact' | 'ambiguous'
  candidates: RelationCandidate[]
  snapshotId: string
  hostRevision: number
}

export interface FilterResult {
  ok: boolean
  operation: 'odoo.apply_filter'
  label: string
  domain: unknown[]
  count: number
  candidates: RecordCandidate[]
  snapshotId: string
  hostRevision: number
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content?: unknown
  hidden?: boolean
  name?: string
  streaming_error?: string
  streamingError?: boolean
  toolCallId?: string
  tool_call_id?: string
  toolCalls?: unknown[]
  tool_calls?: ToolCall[]
  extra_data?: {
    reasoning_steps?: ReasoningStep[]
    reasoning_messages?: ReasoningStep[]
    references?: ReferenceGroup[]
    [key: string]: unknown
  }
  references?: ReferenceGroup[]
  created_at?: string | number
  images?: MediaItem[]
  videos?: MediaItem[]
  audio?: MediaItem[]
  response_audio?: {
    transcript?: string
    content?: string
    url?: string
    mime_type?: string
  }
  attachments?: AttachmentRef[]
  menuMention?: MenuMention
  recordSelection?: RecordSelection
}

export type AttachmentModality = 'image' | 'document'

export interface AttachmentRef {
  id: string
  name: string
  mimeType: string
  size: number
  modality: AttachmentModality
}

export interface AttachmentOptions {
  enabled?: boolean
  maxFileSize?: number
  maxFiles?: number
  maxTotalSize?: number
}

export interface Suggestion {
  title: string
  message: string
}

export interface ChatLabels {
  inputPlaceholder: string
  emptyTitle: string
  emptyDescription: string
  newSession: string
  copyResponse: string
  copied: string
  regenerateResponse: string
  approve: string
  reject: string
  attachments: string
  uploadedAttachments: string
  clearAttachments: string
  addAttachments: string
  removeAttachment: string
  sendMessage: string
  stopGenerating: string
  generatingResponse: string
  positiveFeedback: string
  negativeFeedback: string
  filePreview: string
  closeFilePreview: string
  openFile: string
  previewUnavailable: string
  relationCandidates: string
  relationNoResults: string
  relationSelectionExpired: string
  confirmRelationSelection: string
  selectedRelationCount: string
}

export interface ChatIcons {
  assistant: React.ReactNode
  user: React.ReactNode
  send: React.ReactNode
  stop: React.ReactNode
  upload: React.ReactNode
  copy: React.ReactNode
  complete: React.ReactNode
  regenerate: React.ReactNode
  activity: React.ReactNode
}

export type ChatFeedback = 'positive' | 'negative' | null

export type ChatInteractionEvent =
  | {
      type: 'send'
      content: string
      attachments: AttachmentRef[]
      menuMention?: MenuMention
      recordSelection?: RecordSelection
    }
  | { type: 'stop' }
  | { type: 'copy'; message: ChatMessage }
  | { type: 'regenerate'; message: ChatMessage }
  | { type: 'feedback'; message: ChatMessage; feedback: ChatFeedback }
  | { type: 'suggestion'; suggestion: Suggestion }

export interface AssistantMessageProps {
  message: ChatMessage
  running: boolean
  isCurrent: boolean
  labels: ChatLabels
  icons: ChatIcons
  feedback: ChatFeedback
  toolRenderers?: Record<string, ToolRenderer>
  onCopy: () => void
  onRegenerate: () => void
  onFeedback: (feedback: Exclude<ChatFeedback, null>) => void
  onConfirmTool: (tool: ToolCall, approved: boolean) => void
  onUndoTool?: (tool: ToolCall) => void
  hostState: OdooHostSnapshot
  onSelectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => void
  onSelectRecord: (tool: ToolCall, candidate: RecordCandidate) => void
}

export interface UserMessageProps {
  message: ChatMessage
  icons: ChatIcons
  labels: ChatLabels
  onPreviewAttachment: (attachment: AttachmentRef) => void
  onRemoveMenuMention?: () => void
}

export interface ErrorMessageProps {
  error: string
}

export interface ChatComponents {
  AssistantMessage?: React.ComponentType<AssistantMessageProps>
  UserMessage?: React.ComponentType<UserMessageProps>
  ErrorMessage?: React.ComponentType<ErrorMessageProps>
}

export type ToolRenderer = React.ComponentType<{ tool: ToolCall }>

export interface MediaItem {
  url?: string
  content?: string
  base64_audio?: string
  mime_type?: string
  revised_prompt?: string
  id?: string | number
}

export interface SessionEntry {
  id: string | number
  name?: string
  thread_id: string
  agent_id?: string | false
  surface?: ChatSurface
  write_date?: string | false
  sessionRevision?: number
}

export interface LoadedSession extends SessionEntry {
  protocol?: typeof AGUI_ODOO_PROTOCOL
  messages?: ChatMessage[]
  agentState?: Record<string, unknown>
  uiPreferences?: Record<string, unknown>
}

export interface HostBridgeToolCall {
  id?: string | false
  tool: string
  arguments?: unknown
  message_id?: string | false
  context?: {
    requestId: string
    runId: string
    threadId: string
  }
}

export interface SessionApi {
  list?: () => Promise<{ sessions?: SessionEntry[] } | SessionEntry[]>
  create?: (values?: Record<string, unknown>) => Promise<{ session?: LoadedSession } | LoadedSession>
  load?: (sessionId: string | number) => Promise<{ session?: LoadedSession } | LoadedSession>
  save?: (
    sessionId: string | number | false,
    values: Record<string, unknown>
  ) => Promise<{ session?: LoadedSession } | LoadedSession | void>
  archive?: (sessionId: string | number) => Promise<unknown>
}

export interface HostBridge {
  executeTool?: (call: HostBridgeToolCall) => Promise<unknown> | unknown
  confirmTool?: (
    call: HostBridgeToolCall, authorizationId: string, approved: boolean
  ) => Promise<unknown> | unknown
  undoTool?: (authorizationId: string) => Promise<unknown> | unknown
  listSessions?: SessionApi['list']
  createSession?: SessionApi['create']
  loadSession?: SessionApi['load']
  saveSession?: SessionApi['save']
  archiveSession?: SessionApi['archive']
  openSurface?: (surface: ChatSurface) => Promise<unknown> | unknown
}

export interface AguiChatProps {
  runtimeUrl?: string
  allowCrossOriginDev?: boolean
  agentId?: string
  threadId?: string
  user?: unknown
  context?: unknown
  headers?: HeadersInit
  credentials?: RequestCredentials
  limits?: {
    requestBytes?: number
    messages?: number
    sseEventBytes?: number
  }
  handshake: ProtocolHandshake
  hostState: OdooHostSnapshot
  agentState: Record<string, unknown>
  hostBridge?: HostBridge
  tools: AguiClientTool[]
  menuOptions: MenuMentionOption[]
  resume?: unknown[]
  ui?: {
    initialSidebarCollapsed?: boolean
  }
  onEvent?: (event: unknown) => void
  onError?: (error: unknown) => void
  onTransportStateChange?: (state: TransportState) => void
  onMessagesChange?: (messages: ChatMessage[]) => void
  onAgentStateChange?: (state: Record<string, unknown>) => void
  onSessionChange?: (session: LoadedSession | null) => void
  onRunningChange?: (running: boolean) => void
  sessions?: SessionEntry[]
  session?: LoadedSession | null
  initialMessages?: ChatMessage[]
  surface: ChatSurface
  maxToolFollowups?: number
  attachments?: boolean | AttachmentOptions
  suggestions?: Suggestion[]
  toolRenderers?: Record<string, ToolRenderer>
  labels?: Partial<ChatLabels>
  icons?: Partial<ChatIcons>
  components?: ChatComponents
  onFeedback?: (message: ChatMessage, feedback: ChatFeedback) => void
  onInteraction?: (event: ChatInteractionEvent) => void
  __debug?: boolean
}

export interface RuntimeSnapshot {
  messages: ChatMessage[]
  sessions: SessionEntry[]
  session: LoadedSession | null
  hostState: OdooHostSnapshot
  agentState: Record<string, unknown>
  threadId: string
  running: boolean
  transportState: TransportState | null
  loadingSessions: boolean
  error: string
}

export interface MountHandle {
  update: (nextProps: Partial<AguiChatProps>) => void
  unmount: () => void
  __runtime?: unknown
}

export interface AguiChatApi {
  mount: (el: Element, props: AguiChatProps) => MountHandle
  version: string
  protocol: typeof AGUI_ODOO_PROTOCOL
}
