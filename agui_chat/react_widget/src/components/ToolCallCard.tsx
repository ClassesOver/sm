import { ChevronRight, Hammer, RotateCcw } from 'lucide-react'
import type {
  ChatLabels, FilterResult, OdooHostSnapshot, RecordCandidate, RelationCandidate,
  RelationSearchResult, ToolCall, ToolRenderer
} from '../types'
import { toolName } from '../runtime/utils'
import { Button } from './Button'
import { CandidateOption, CandidatePanel } from './CandidatePanel'
import { InlineNotice } from './InlineNotice'
import { RenderErrorBoundary } from './RenderErrorBoundary'
import { ToolConfirmationPreview } from './ToolConfirmationPreview'
import { ToolStatusBadge } from './ToolStatusBadge'
import { getBuiltInToolPresentation } from './builtInToolPresentation'
import { getToolCallPresentation } from './toolCallPresentation'
import {
  isCandidateSnapshotStale,
  useRelationCandidateSelection
} from './useRelationCandidateSelection'

interface ToolCallCardProps {
  tool: ToolCall
  renderers?: Record<string, ToolRenderer>
  onConfirm: (approved: boolean) => void
  onUndo: () => void
  labels: ChatLabels
  hostState: OdooHostSnapshot
  running: boolean
  onSelectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => void
  onSelectRecord: (tool: ToolCall, candidate: RecordCandidate) => void
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
  const selection = useRelationCandidateSelection(result)
  const stale = isCandidateSnapshotStale(result, hostState)
  const multiple = result.fieldType === 'many2many'

  return <CandidatePanel
    title={result.fieldLabel || result.field}
    description={`${labels.relationCandidates} · ${result.relation}`}
    badge={result.query}
    emptyMessage={labels.relationNoResults}
    notice={stale ? <InlineNotice className="mt-3" tone="warning">{labels.relationSelectionExpired}</InlineNotice> : null}
    footer={multiple && result.candidates.length ? <div className="mt-3 flex items-center justify-between gap-3">
      <span className="text-[11px] text-muted">{labels.selectedRelationCount.replace('{count}', String(selection.selectedCandidates.length))}</span>
      <Button size="sm" variant="primary" className="h-8 rounded-md" disabled={stale || running || !selection.selectedCandidates.length} onClick={() => onSelect(tool, selection.selectedCandidates)}>{labels.confirmRelationSelection}</Button>
    </div> : null}
  >
    {result.candidates.map((candidate) => {
      const disabled = stale || running || !selection.isCompatible(candidate)
      return multiple ? (
        <label key={candidate.id} className="flex min-h-9 items-center gap-2 rounded border border-border bg-background px-2.5 py-1.5 text-xs text-primary has-[:disabled]:opacity-45">
          <input type="checkbox" className="size-4" disabled={disabled} checked={selection.selectedIds.includes(candidate.id)} onChange={() => selection.toggleCandidate(candidate)} />
          <span className="min-w-0 flex-1 truncate">{candidate.displayName}</span>
          <span className="shrink-0 text-[10px] text-muted">#{candidate.id}</span>
        </label>
      ) : (
        <CandidateOption key={candidate.id} disabled={disabled} onClick={() => onSelect(tool, [candidate])} trailing={<span className="shrink-0 text-[10px] text-muted">#{candidate.id}</span>}>
          {candidate.displayName}
        </CandidateOption>
      )
    })}
  </CandidatePanel>
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
  const stale = isCandidateSnapshotStale(result, hostState)
  return <CandidatePanel
    title={result.label}
    description={`匹配 ${result.count} 条记录`}
    badge="选择记录"
    emptyMessage="没有可选择的可见记录。"
    notice={stale ? <InlineNotice className="mt-3" tone="warning">候选快照已过期，请重新筛选。</InlineNotice> : null}
  >
    {result.candidates.map((candidate) => <CandidateOption key={candidate.token} disabled={stale || running} onClick={() => onSelect(tool, candidate)} trailing={<ChevronRight className="size-3.5 shrink-0 text-muted" />}>
      {candidate.displayName}
    </CandidateOption>)}
  </CandidatePanel>
}

function DefaultToolCallCard({ tool, onConfirm, onUndo, labels, running }: {
  tool: ToolCall
  onConfirm: (approved: boolean) => void
  onUndo: () => void
  labels: ChatLabels
  running: boolean
}) {
  const {
    displayName, result, applied, rejected, status, error, needsConfirmation, undo, call
  } = getToolCallPresentation(tool)
  return (
    <details open={needsConfirmation || undefined} className="rounded-lg border border-border bg-background-secondary/80 p-2">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-md bg-background px-2 py-1 font-mono text-[11px] text-primary">
          <Hammer className="size-3" />{displayName}
        </span>
        <ToolStatusBadge status={status} />
        {applied || rejected ? <span className="rounded-md bg-background px-2 py-1 text-[11px] text-muted">已应用 {applied} 项 / 已拒绝 {rejected} 项</span> : null}
      </summary>
      {error ? <InlineNotice className="mt-2" tone="error">{String(error)}</InlineNotice> : null}
      {needsConfirmation ? <div className="mt-2 rounded-md border border-solid border-warning/25 bg-warning/10 p-2 text-xs text-warning">
        <div>需要确认：{displayName}</div>
        <ToolConfirmationPreview result={result} />
        <div className="mt-2 flex gap-2">
          <Button size="sm" variant="primary" className="h-7 rounded-md" disabled={running} onClick={() => onConfirm(true)}>{labels.approve}</Button>
          <Button size="sm" className="h-7 rounded-md bg-background-panel" disabled={running} onClick={() => onConfirm(false)}>{labels.reject}</Button>
        </div>
      </div> : null}
      {undo.available ? <div className="mt-2 flex items-center gap-2 border-t border-border pt-2"><Button size="sm" className="h-8 rounded-md bg-background" disabled={running || undo.status === 'running' || undo.status === 'undone'} title="撤销本次修改" onClick={onUndo}><RotateCcw className="size-3.5" />{undo.status === 'running' ? '撤销中' : undo.status === 'undone' ? '已撤销' : '撤销'}</Button>{undo.error ? <span className="text-xs text-destructive">{String(undo.error)}</span> : null}</div> : null}
      <details className="mt-2 border-t border-border pt-2">
        <summary className="cursor-pointer text-xs text-muted">查看详情</summary>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <pre className="max-h-52 overflow-auto rounded-md bg-background p-2 text-[11px] text-muted">{JSON.stringify(call, null, 2)}</pre>
          <pre className="max-h-52 overflow-auto rounded-md bg-background p-2 text-[11px] text-muted">{JSON.stringify(tool.result || null, null, 2)}</pre>
        </div>
      </details>
    </details>
  )
}

export function ToolCallCard({
  tool, renderers, onConfirm, onUndo, labels, hostState, running,
  onSelectRelation, onSelectRecord
}: ToolCallCardProps) {
  const Renderer = renderers?.[toolName(tool)]
  const fallback = <DefaultToolCallCard tool={tool} onConfirm={onConfirm} onUndo={onUndo} labels={labels} running={running} />
  if (Renderer) return <RenderErrorBoundary
    fallback={fallback}
    resetKeys={[
      Renderer,
      tool.id,
      tool.key,
      tool.status,
      tool.result,
      tool.error,
      tool.args,
      tool.tool_args,
      tool.argsText
    ]}
  >
    <Renderer tool={tool} />
  </RenderErrorBoundary>
  const builtIn = getBuiltInToolPresentation(tool)
  if (builtIn.kind === 'relation_search') {
    return <RelationSearchCard tool={tool} result={builtIn.result} labels={labels} hostState={hostState} running={running} onSelect={onSelectRelation} />
  }
  if (builtIn.kind === 'record_candidates') {
    return <RecordCandidatesCard tool={tool} result={builtIn.result} hostState={hostState} running={running} onSelect={onSelectRecord} />
  }
  return fallback
}
