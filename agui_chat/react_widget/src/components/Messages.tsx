import React, { useEffect, useState } from 'react'
import {
  AtSign, CheckCircle2, ChevronRight, CircleAlert, Clock3, Database, FileText,
  Filter as FilterIcon, Folder, Hammer, Loader2, Menu, RotateCcw, SlidersHorizontal, Sparkles, Workflow, X
} from 'lucide-react'
import type {
  AssistantMessageProps, AttachmentRef, ChatComponents, ChatFeedback, ChatIcons,
  ChatLabels, ChatMessage, FilterResult, OdooHostSnapshot, RecordCandidate, ReferenceGroup,
  RelationCandidate, RelationSearchResult, ReasoningStep, Suggestion, ToolCall, ToolRenderer,
  ToolStatus, UserMessageProps
} from '../types'
import { cn } from '../lib'
import { asText, normalizeReferenceGroups, toolArgs, toolCallId, toolName, visibleMessages } from '../runtime/utils'
import { Markdown } from './Markdown'

export interface MessagesProps {
  messages: ChatMessage[]
  running: boolean
  onConfirmTool: (tool: ToolCall, approved: boolean) => void
  onUndoTool?: (tool: ToolCall) => void
  suggestions?: Suggestion[]
  toolRenderers?: Record<string, ToolRenderer>
  onRegenerate: (messageId: string) => void
  onSuggestion: (suggestion: Suggestion) => void
  labels: ChatLabels
  icons: ChatIcons
  components?: ChatComponents
  onCopy: (message: ChatMessage) => void
  onFeedback: (message: ChatMessage, feedback: ChatFeedback) => void
  onPreviewAttachment: (attachment: AttachmentRef) => void
  hostState: OdooHostSnapshot
  onSelectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => void
  onSelectRecord: (tool: ToolCall, candidate: RecordCandidate) => void
  onRemoveMenuMention?: (messageId: string) => void
  onRemoveMention?: (messageId: string, referenceId: string) => void
}

function statusIcon(status?: ToolStatus) {
  if (status === 'running') return <Loader2 className="size-3 animate-spin" />
  if (status === 'ok') return <CheckCircle2 className="size-3" />
  if (status === 'error' || status === 'cancelled') return <CircleAlert className="size-3" />
  return <Clock3 className="size-3" />
}

function statusClass(status?: ToolStatus): string {
  if (status === 'ok') return 'border-positive/30 bg-positive/10 text-positive'
  if (status === 'error' || status === 'cancelled') return 'border-destructive/35 bg-destructive/10 text-destructive'
  if (status === 'needs_confirmation') return 'border-warning/35 bg-warning/10 text-warning'
  return 'border-primary/15 bg-accent text-muted'
}

function statusLabel(status?: ToolStatus): string {
  if (status === 'running') return '执行中'
  if (status === 'ok') return '已完成'
  if (status === 'error') return '出错'
  if (status === 'cancelled') return '已取消'
  if (status === 'needs_confirmation') return '待确认'
  return '等待中'
}

function RelationSearchCard({
  tool, result, labels, hostState, running, onSelect
}: {
  tool: ToolCall
  result: RelationSearchResult
  labels: ChatLabels
  hostState: OdooHostSnapshot
  running: boolean
  onSelect: (tool: ToolCall, candidates: RelationCandidate[]) => void
}) {
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const stale = result.snapshotId !== hostState.snapshotId || result.hostRevision !== hostState.hostRevision
  const multiple = result.fieldType === 'many2many'
  const compatible = (candidate: RelationCandidate) =>
    result.relationOperation === 'link' ? !candidate.selected :
    result.relationOperation === 'unlink' ? candidate.selected : true

  useEffect(() => setSelectedIds([]), [result.snapshotId, result.hostRevision, result.query])

  const toggle = (candidate: RelationCandidate) => {
    setSelectedIds((current) => current.includes(candidate.id)
      ? current.filter((id) => id !== candidate.id)
      : [...current, candidate.id])
  }
  const selected = result.candidates.filter((candidate) => selectedIds.includes(candidate.id))

  return <div className="rounded-lg border border-border bg-background-secondary/80 p-3">
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="truncate text-xs font-semibold text-primary">{result.fieldLabel || result.field}</div>
        <div className="mt-0.5 truncate text-[11px] text-muted">{labels.relationCandidates} · {result.relation}</div>
      </div>
      <span className="shrink-0 rounded border border-border bg-background px-2 py-1 text-[10px] text-muted">{result.query}</span>
    </div>
    {stale ? <div className="mt-3 rounded border border-warning/30 bg-warning/10 p-2 text-xs text-warning">{labels.relationSelectionExpired}</div> : null}
    {!result.candidates.length ? <div className="mt-3 text-xs text-muted">{labels.relationNoResults}</div> : (
      <div className="mt-3 grid gap-1.5">
        {result.candidates.map((candidate) => {
          const disabled = stale || running || !compatible(candidate)
          return multiple ? (
            <label key={candidate.id} className="flex min-h-9 items-center gap-2 rounded border border-border bg-background px-2.5 py-1.5 text-xs text-primary has-[:disabled]:opacity-45">
              <input type="checkbox" className="size-4" disabled={disabled} checked={selectedIds.includes(candidate.id)} onChange={() => toggle(candidate)} />
              <span className="min-w-0 flex-1 truncate">{candidate.displayName}</span>
              <span className="shrink-0 text-[10px] text-muted">#{candidate.id}</span>
            </label>
          ) : (
            <button key={candidate.id} type="button" disabled={disabled} className="flex min-h-9 items-center gap-2 rounded border border-solid border-border bg-background px-2.5 py-1.5 text-left text-xs text-primary hover:bg-accent disabled:opacity-45" onClick={() => onSelect(tool, [candidate])}>
              <span className="min-w-0 flex-1 truncate">{candidate.displayName}</span>
              <span className="shrink-0 text-[10px] text-muted">#{candidate.id}</span>
            </button>
          )
        })}
      </div>
    )}
    {multiple && result.candidates.length ? <div className="mt-3 flex items-center justify-between gap-3">
      <span className="text-[11px] text-muted">{labels.selectedRelationCount.replace('{count}', String(selected.length))}</span>
      <button type="button" disabled={stale || running || !selected.length} className="h-8 rounded-md border border-solid border-primary bg-primary px-3 text-xs text-primaryAccent disabled:opacity-40" onClick={() => onSelect(tool, selected)}>{labels.confirmRelationSelection}</button>
    </div> : null}
  </div>
}

function RecordCandidatesCard({
  tool, result, hostState, running, onSelect
}: {
  tool: ToolCall
  result: FilterResult
  hostState: OdooHostSnapshot
  running: boolean
  onSelect: (tool: ToolCall, candidate: RecordCandidate) => void
}) {
  const stale = result.snapshotId !== hostState.snapshotId || result.hostRevision !== hostState.hostRevision
  return <div className="rounded-lg border border-border bg-background-secondary/80 p-3">
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="truncate text-xs font-semibold text-primary">{result.label}</div>
        <div className="mt-0.5 text-[11px] text-muted">匹配 {result.count} 条记录</div>
      </div>
      <span className="shrink-0 rounded border border-border bg-background px-2 py-1 text-[10px] text-muted">选择记录</span>
    </div>
    {stale ? <div className="mt-3 rounded border border-warning/30 bg-warning/10 p-2 text-xs text-warning">候选快照已过期，请重新筛选。</div> : null}
    {!result.candidates.length ? <div className="mt-3 text-xs text-muted">没有可选择的可见记录。</div> : <div className="mt-3 grid gap-1.5">
      {result.candidates.map((candidate) => <button key={candidate.token} type="button" disabled={stale || running} className="flex min-h-9 items-center gap-2 rounded border border-solid border-border bg-background px-2.5 py-1.5 text-left text-xs text-primary hover:bg-accent disabled:opacity-45" onClick={() => onSelect(tool, candidate)}>
        <span className="min-w-0 flex-1 truncate">{candidate.displayName}</span>
        <ChevronRight className="size-3.5 shrink-0 text-muted" />
      </button>)}
    </div>}
  </div>
}

function displayDiffValue(value: unknown): string {
  if (value === false || value === null || value === undefined || value === '') return '空'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function ConfirmationPreview({ result }: { result: Record<string, unknown> }) {
  const preview = result.preview && typeof result.preview === 'object'
    ? result.preview as Record<string, unknown> : {}
  const changes = Array.isArray(preview.changes)
    ? preview.changes as Array<Record<string, unknown>> : []
  const riskLabels: Record<string, string> = {
    multiple_fields: '多字段修改',
    relation_field: '关系字段',
    policy_high_risk_field: '管理员标记字段',
    field_type_unknown: '字段类型未确认',
    destructive_command: '写入操作',
    object_button: '对象按钮'
  }
  const reasons = Array.isArray(preview.riskReasons) ? preview.riskReasons : []
  const control = preview.control && typeof preview.control === 'object'
    ? preview.control as Record<string, unknown> : null
  if (control) {
    return <div className="mt-2 rounded border border-warning/25 bg-background p-2 text-xs text-primary">
      <div className="font-semibold">{String(control.label || '对象按钮')}</div>
      <div className="mt-1 text-muted">所属记录：{String(control.recordLabel || '当前记录')}</div>
    </div>
  }
  if (!changes.length) {
    return <pre className="mt-2 max-h-52 overflow-auto rounded bg-background p-2 text-[11px]">{JSON.stringify({ target: result.target || {}, patch: result.patch || {} }, null, 2)}</pre>
  }
  return <div className="mt-2 overflow-hidden rounded border border-warning/25 bg-background text-primary">
    {changes.map((change) => <div key={String(change.field)} className="grid gap-1 border-b border-border p-2 last:border-b-0">
      <div className="text-[11px] font-semibold">{String(change.label || change.field)}</div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2 text-[11px]">
        <span className="break-words text-muted">{displayDiffValue(change.oldValue)}</span>
        <ChevronRight className="mt-0.5 size-3 text-muted" />
        <span className="break-words">{displayDiffValue(change.newValue)}</span>
      </div>
    </div>)}
    {reasons.length ? <div className="flex flex-wrap gap-1 border-t border-warning/20 p-2">{reasons.map((reason) => <span key={String(reason)} className="rounded border border-warning/25 px-1.5 py-0.5 text-[10px] text-warning">{riskLabels[String(reason)] || String(reason)}</span>)}</div> : null}
  </div>
}

function ToolCard({ tool, onConfirm, onUndo, labels, running }: {
  tool: ToolCall
  onConfirm: (approved: boolean) => void
  onUndo: () => void
  labels: ChatLabels
  running: boolean
}) {
  const names: Record<string, string> = {
    'odoo.open_menu': '打开菜单',
    'odoo.apply_filter': '筛选当前视图',
    'odoo.open_record': '打开记录',
    'odoo.open_create': '新建记录',
    'odoo.enter_edit_mode': '进入编辑模式',
    'odoo.activate_view_control': '激活页面控件',
    'odoo.search_relation': '查询关系记录',
    'odoo.stage_current_form': '暂存当前表单',
    'odoo.patch_current_form': '修改当前表单',
    'odoo.validate_current_form': '校验当前表单',
    'odoo.save_current_form': '保存当前表单',
    'odoo.discard_current_form': '放弃表单更改'
  }
  const displayName = names[toolName(tool)] || toolName(tool)
  const result = tool.result && typeof tool.result === 'object' ? tool.result as Record<string, unknown> : {}
  const applied = Array.isArray(result.applied) ? result.applied.length : 0
  const rejected = Array.isArray(result.rejected) ? result.rejected.length : 0
  const status = tool.status || 'pending'
  const receipt = result.receipt && typeof result.receipt === 'object'
    ? result.receipt as Record<string, unknown> : {}
  const undo = receipt.undo && typeof receipt.undo === 'object'
    ? receipt.undo as Record<string, unknown> : {}
  return (
    <details open={status === 'needs_confirmation' || !!tool.needs_confirmation || undefined} className="rounded-lg border border-border bg-background-secondary/80 p-2">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-md bg-background px-2 py-1 font-mono text-[11px] text-primary">
          <Hammer className="size-3" />{displayName}
        </span>
        <span className={cn('inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] uppercase', statusClass(status))}>
          {statusIcon(status)}{statusLabel(status)}
        </span>
      {applied || rejected ? <span className="rounded-md bg-background px-2 py-1 text-[11px] text-muted">已应用 {applied} 项 / 已拒绝 {rejected} 项</span> : null}
      </summary>
      {tool.error || result.error ? <div className="mt-2 rounded-md border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">{String(tool.error || result.error)}</div> : null}
      {status === 'needs_confirmation' || tool.needs_confirmation ? <div className="mt-2 rounded-md border border-solid border-warning/25 bg-warning/10 p-2 text-xs text-warning"><div>需要确认：{displayName}</div><ConfirmationPreview result={result} /><div className="mt-2 flex gap-2"><button type="button" disabled={running} className="rounded-md border border-solid border-primary bg-primary px-2 py-1 text-primaryAccent disabled:opacity-45" onClick={() => onConfirm(true)}>{labels.approve}</button><button type="button" disabled={running} className="rounded-md border border-solid border-border bg-background-panel px-2 py-1 disabled:opacity-45" onClick={() => onConfirm(false)}>{labels.reject}</button></div></div> : null}
      {undo.available ? <div className="mt-2 flex items-center gap-2 border-t border-border pt-2"><button type="button" disabled={running || undo.status === 'running' || undo.status === 'undone'} title="撤销本次修改" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-solid border-border bg-background px-2.5 text-xs text-primary hover:bg-accent disabled:opacity-45" onClick={onUndo}><RotateCcw className="size-3.5" />{undo.status === 'running' ? '撤销中' : undo.status === 'undone' ? '已撤销' : '撤销'}</button>{undo.error ? <span className="text-xs text-destructive">{String(undo.error)}</span> : null}</div> : null}
      <details className="mt-2 border-t border-border pt-2">
        <summary className="cursor-pointer text-xs text-muted">查看详情</summary>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <pre className="max-h-52 overflow-auto rounded-md bg-background p-2 text-[11px] text-muted">{JSON.stringify({ id: toolCallId(tool), args: toolArgs(tool) }, null, 2)}</pre>
          <pre className="max-h-52 overflow-auto rounded-md bg-background p-2 text-[11px] text-muted">{JSON.stringify(tool.result || null, null, 2)}</pre>
        </div>
      </details>
    </details>
  )
}

class ToolRendererBoundary extends React.Component<
  { children: React.ReactNode; fallback: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}

function RenderTool({ tool, renderers, onConfirm, onUndo, labels, hostState, running, onSelectRelation, onSelectRecord }: {
  tool: ToolCall
  renderers?: Record<string, ToolRenderer>
  onConfirm: (approved: boolean) => void
  onUndo: () => void
  labels: ChatLabels
  hostState: OdooHostSnapshot
  running: boolean
  onSelectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => void
  onSelectRecord: (tool: ToolCall, candidate: RecordCandidate) => void
}) {
  const Renderer = renderers?.[toolName(tool)]
  const fallback = <ToolCard tool={tool} onConfirm={onConfirm} onUndo={onUndo} labels={labels} running={running} />
  if (Renderer) return <ToolRendererBoundary fallback={fallback}><Renderer tool={tool} /></ToolRendererBoundary>
  const result = tool.result && typeof tool.result === 'object' ? tool.result as RelationSearchResult : null
  if (toolName(tool) === 'odoo.search_relation' && result?.ok && Array.isArray(result.candidates)) {
    return <RelationSearchCard tool={tool} result={result} labels={labels} hostState={hostState} running={running} onSelect={onSelectRelation} />
  }
  if (toolName(tool) === 'odoo.apply_filter' && result?.ok && Array.isArray(result.candidates)) {
    return <RecordCandidatesCard tool={tool} result={result as unknown as FilterResult} hostState={hostState} running={running} onSelect={onSelectRecord} />
  }
  return fallback
}

function Reasoning({ steps }: { steps: ReasoningStep[] }) {
  if (!steps.length) return null
  return (
    <div className="flex items-start gap-3">
      <Workflow className="mt-0.5 size-5 shrink-0 text-muted" />
      <div className="flex flex-col gap-2">
        <div className="text-xs font-medium uppercase text-muted">思考过程</div>
        {steps.map((step, index) => (
          <details key={`${step.title}-${index}`} className="rounded-lg border border-border bg-accent px-3 py-2 text-sm">
            <summary className="cursor-pointer text-xs text-primary">步骤 {index + 1}：{step.title}</summary>
            {step.content ? <div className="mt-2 text-xs leading-5 text-muted">{step.content}</div> : null}
          </details>
        ))}
      </div>
    </div>
  )
}

function References({ references }: { references: ReferenceGroup[] }) {
  const groups = normalizeReferenceGroups(references)
  if (!groups.length) return null
  return <div className="flex flex-col gap-3">{groups.map((group, groupIndex) => (
    <div key={`${group.query || 'references'}-${groupIndex}`} className="flex flex-wrap gap-2">
      {group.references.map((reference, index) => {
        const body = <div className="h-20 w-48 overflow-hidden rounded-lg border border-border bg-accent p-3 hover:bg-background-secondary">
          <div className="truncate text-sm font-medium text-primary">{reference.name}</div>
          {reference.content ? <div className="mt-2 line-clamp-2 text-xs leading-4 text-muted">{reference.content}</div> : null}
        </div>
        return reference.url ? <a key={`${reference.name}-${index}`} href={reference.url} target="_blank" rel="noopener noreferrer">{body}</a> : <div key={`${reference.name}-${index}`}>{body}</div>
      })}
    </div>
  ))}</div>
}

function attachmentUrl(attachment: AttachmentRef) {
  return `/agui_chat/attachment/${encodeURIComponent(attachment.id)}`
}

function attachmentMeta(attachment: AttachmentRef): string {
  const type = attachment.mimeType.includes('pdf') ? 'PDF' : attachment.mimeType.split('/').pop()?.toUpperCase() || 'FILE'
  const size = attachment.size < 1024 * 1024
    ? `${Math.max(1, Math.round(attachment.size / 1024))} KB`
    : `${(attachment.size / (1024 * 1024)).toFixed(2)} MB`
  return `${type} Document · ${size}`
}

function Attachments({ attachments, labels, onPreview }: { attachments?: AttachmentRef[]; labels: ChatLabels; onPreview: (attachment: AttachmentRef) => void }) {
  if (!attachments?.length) return null
  return <div className="mb-2 flex flex-wrap justify-end gap-2">{attachments.map((attachment) => (
    attachment.modality === 'image' ? (
      <button key={attachment.id} type="button" className="border-0 bg-transparent p-0" aria-label={`${labels.filePreview}: ${attachment.name}`} onClick={() => onPreview(attachment)}>
        <img className="h-28 w-40 rounded-lg border border-border object-cover" src={attachmentUrl(attachment)} alt={attachment.name} />
      </button>
    ) : (
      <button key={attachment.id} type="button" className="flex h-14 w-60 max-w-full items-center gap-2 rounded-lg border border-solid border-border bg-background-panel px-2.5 text-left text-xs text-primary hover:bg-background-secondary" aria-label={`${labels.filePreview}: ${attachment.name}`} onClick={() => onPreview(attachment)}>
        <span className="grid size-7 shrink-0 place-items-center rounded bg-background-secondary"><FileText className="size-4" /></span>
        <span className="min-w-0 flex-1"><span className="block truncate">{attachment.name}</span><span className="mt-0.5 block truncate text-[11px] text-muted">{attachmentMeta(attachment)}</span></span>
        <ChevronRight className="size-4 shrink-0 text-muted" />
      </button>
    )
  ))}</div>
}

export function DefaultAssistantMessage({
  message, running, isCurrent, toolRenderers, labels, icons, hostState,
  onCopy, onRegenerate, onConfirmTool, onUndoTool = () => undefined, onSelectRelation,
  onSelectRecord
}: AssistantMessageProps) {
  const [copied, setCopied] = useState(false)
  const content = asText(message.content)
  const reasoning = message.extra_data?.reasoning_steps || []
  const references = message.extra_data?.references || []
  const copy = async () => {
    await onCopy()
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }
  return <div className="flex flex-col gap-5">
    <Reasoning steps={reasoning} />
    <References references={references} />
    {message.tool_calls?.length ? <div className="flex flex-col gap-2">{message.tool_calls.map((tool, index) => (
      <RenderTool key={tool.key || toolCallId(tool) || `${toolName(tool)}-${index}`} tool={tool} renderers={toolRenderers} labels={labels} hostState={hostState} running={running} onSelectRelation={onSelectRelation} onSelectRecord={onSelectRecord} onConfirm={(approved) => onConfirmTool(tool, approved)} onUndo={() => onUndoTool(tool)} />
    ))}</div> : null}
    {content || message.streaming_error ? <div className="group flex items-start gap-3">
      <div className="grid size-6 shrink-0 place-items-center rounded bg-primary text-primaryAccent">{icons.assistant}</div>
      <div className="min-w-0 flex-1">
        {message.streaming_error ? <div className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{message.streaming_error}</div> : null}
        {content ? <Markdown>{content}</Markdown> : null}
        <div className={cn(
          'agui-message-controls mt-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100',
          isCurrent && 'opacity-100'
        )}>
          <button type="button" className="grid size-7 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-accent hover:text-primary" aria-label={copied ? labels.copied : labels.copyResponse} title={labels.copyResponse} onClick={() => void copy()}>{copied ? icons.complete : icons.copy}</button>
          <button type="button" className="grid size-7 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-accent hover:text-primary disabled:opacity-40" disabled={running} aria-label={labels.regenerateResponse} title={labels.regenerateResponse} onClick={onRegenerate}>{icons.regenerate}</button>
        </div>
      </div>
    </div> : null}
  </div>
}

export function DefaultUserMessage({ message, labels, onPreviewAttachment, onRemoveMenuMention, onRemoveMention }: UserMessageProps) {
  const mention = message.menuMention
  const actionLabels = {
    read: '引用数据', open: '打开', create: '新建', view: '查看', edit: '编辑', apply: '应用'
  }
  const mentionIcon = (kind: string) => {
    if (kind === 'menu') return <Menu className="size-3.5 shrink-0" />
    if (kind === 'record') return <Database className="size-3.5 shrink-0" />
    if (kind === 'saved_filter') return <FilterIcon className="size-3.5 shrink-0" />
    return <SlidersHorizontal className="size-3.5 shrink-0" />
  }
  return <div className="flex w-full justify-end">
    <div className="min-w-0 max-w-[82%]">
      <Attachments attachments={message.attachments} labels={labels} onPreview={onPreviewAttachment} />
      {message.mentions?.length ? <div className="mb-2 flex flex-wrap justify-end gap-1.5">
        {message.mentions.map((reference) => <span key={reference.id} className={cn(
          'inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
          reference.valid ? 'border-primary/20 bg-accent text-primary' : 'border-warning/35 bg-warning/10 text-warning'
        )} title={reference.detail}>
          {mentionIcon(reference.kind)}
          <span className="truncate">{reference.label}</span>
          <span className="shrink-0 opacity-70">{actionLabels[reference.action]}</span>
          {!reference.valid ? <span className="shrink-0">（已失效）</span> : null}
          {onRemoveMention ? <button type="button" className="grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-current opacity-65 hover:bg-background hover:opacity-100" aria-label={`移除引用 ${reference.label}`} title="移除引用" onClick={() => onRemoveMention(reference.id)}><X className="size-3" /></button> : null}
        </span>)}
      </div> : null}
      {message.workspaceReferences?.length ? <div className="mb-2 flex flex-wrap justify-end gap-1.5" aria-label="消息工作区引用">
        {message.workspaceReferences.map((reference) => <span key={reference.id} className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border bg-background-panel px-2 py-1 text-xs text-primary" title={reference.path}>
          {reference.isDirectory ? <Folder className="size-3.5 shrink-0" /> : <FileText className="size-3.5 shrink-0" />}<span className="truncate">{reference.name}</span>
        </span>)}
      </div> : null}
      {message.skills?.length ? <div className="mb-2 flex flex-wrap justify-end gap-1.5" aria-label="消息技能">
        {message.skills.map((skill) => <span key={skill.id} className={cn(
          'inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
          skill.valid
            ? 'border-emerald-700/20 bg-emerald-50 text-emerald-900'
            : 'border-warning/35 bg-warning/10 text-warning'
        )} title={skill.description}>
          <Sparkles className="size-3.5 shrink-0" />
          <span className="truncate">{skill.name}</span>
          {!skill.valid ? <span className="shrink-0">（已失效）</span> : null}
        </span>)}
      </div> : null}
      {mention ? <div className="mb-2 flex justify-end">
        <span className={cn(
          'inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
          mention.valid ? 'border-primary/20 bg-accent text-primary' : 'border-warning/35 bg-warning/10 text-warning'
        )} title={mention.fullPath}>
          <AtSign className="size-3.5 shrink-0" />
          <span className="truncate">{mention.fullPath}</span>
          {!mention.valid ? <span className="shrink-0">（已失效）</span> : null}
          {onRemoveMenuMention ? <button type="button" className="grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-current opacity-65 hover:bg-background hover:opacity-100" aria-label="移除菜单" title="移除菜单" onClick={onRemoveMenuMention}><X className="size-3" /></button> : null}
        </span>
      </div> : null}
      {asText(message.content) ? <div className="ml-auto w-fit rounded-lg bg-background-secondary px-3.5 py-2 text-sm leading-6 text-secondary">{asText(message.content)}</div> : null}
    </div>
  </div>
}

function Suggestions({ suggestions, disabled, onSelect }: { suggestions?: Suggestion[]; disabled: boolean; onSelect: (suggestion: Suggestion) => void }) {
  if (!suggestions?.length) return null
  return <div className="flex flex-wrap justify-center gap-2">{suggestions.map((suggestion) => (
    <button key={`${suggestion.title}-${suggestion.message}`} type="button" disabled={disabled} className="max-w-64 rounded-lg border border-solid border-border bg-background-secondary px-3 py-2 text-left hover:bg-accent disabled:opacity-40" onClick={() => onSelect(suggestion)}>
      <div className="text-xs font-medium text-primary">{suggestion.title}</div>
      <div className="mt-1 line-clamp-2 text-xs text-muted">{suggestion.message}</div>
    </button>
  ))}</div>
}

export function Messages({
  messages, running, suggestions, toolRenderers, labels, icons, components,
  onRegenerate, onSuggestion, onConfirmTool, onUndoTool, onCopy, onFeedback, onPreviewAttachment,
  hostState, onSelectRelation, onSelectRecord, onRemoveMenuMention, onRemoveMention
}: MessagesProps) {
  const [feedback, setFeedback] = useState<Record<string, ChatFeedback>>({})
  const displayMessages = visibleMessages(messages)
  const lastAssistantIndex = displayMessages.reduce(
    (last, message, index) => message.role === 'assistant' || message.role === 'agent' ? index : last,
    -1
  )
  const AssistantMessage = components?.AssistantMessage || DefaultAssistantMessage
  const UserMessage = components?.UserMessage || DefaultUserMessage
  if (!displayMessages.length) return <div className="flex min-h-[320px] flex-col items-center justify-center px-4 text-center">
    <div className="grid size-12 place-items-center rounded-xl bg-accent text-primary">{icons.assistant}</div>
    <div className="mt-4 text-sm font-medium text-primary">{labels.emptyTitle}</div>
    <div className="mt-1 mb-5 max-w-sm text-sm text-muted">{labels.emptyDescription}</div>
    <Suggestions suggestions={suggestions} disabled={running} onSelect={onSuggestion} />
  </div>
  return <div className="mx-auto flex w-full max-w-3xl flex-col gap-12 px-4 py-8">
    {displayMessages.map((message, index) => {
      const role = message.role === 'agent' ? 'assistant' : message.role
      if (role === 'assistant') return <AssistantMessage key={message.id || `assistant-${index}`} message={message} running={running} isCurrent={index === lastAssistantIndex} toolRenderers={toolRenderers} labels={labels} icons={icons} feedback={feedback[message.id] || null} hostState={hostState} onSelectRelation={(tool, candidates) => onSelectRelation(tool, candidates)} onSelectRecord={(tool, candidate) => onSelectRecord(tool, candidate)} onCopy={() => onCopy(message)} onRegenerate={() => onRegenerate(message.id)} onFeedback={(next) => {
        const value = feedback[message.id] === next ? null : next
        setFeedback((current) => ({ ...current, [message.id]: value }))
        onFeedback(message, value)
      }} onConfirmTool={onConfirmTool} onUndoTool={(tool) => onUndoTool?.(tool)} />
      if (role === 'user') return <UserMessage key={message.id || `user-${index}`} message={message} icons={icons} labels={labels} onPreviewAttachment={onPreviewAttachment} onRemoveMenuMention={message.menuMention && onRemoveMenuMention ? () => onRemoveMenuMention(message.id) : undefined} onRemoveMention={message.mentions?.length && onRemoveMention ? (referenceId) => onRemoveMention(message.id, referenceId) : undefined} />
      return null
    })}
    {running ? <div className="agui-activity flex items-center gap-1.5 py-1" aria-label={labels.generatingResponse}>{[0, 1, 2].map((index) => <React.Fragment key={index}>{icons.activity}</React.Fragment>)}</div> : <Suggestions suggestions={suggestions} disabled={false} onSelect={onSuggestion} />}
  </div>
}
