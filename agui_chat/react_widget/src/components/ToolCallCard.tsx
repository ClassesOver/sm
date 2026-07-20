import React, { useEffect, useState } from 'react'
import { ChevronRight, Hammer, RotateCcw } from 'lucide-react'
import type {
  ChatLabels, FilterResult, OdooHostSnapshot, RecordCandidate, RelationCandidate,
  RelationSearchResult, ToolCall, ToolRenderer
} from '../types'
import { toolArgs, toolCallId, toolName } from '../runtime/utils'
import { Button } from './Button'
import { CandidateOption, CandidatePanel } from './CandidatePanel'
import { InlineNotice } from './InlineNotice'
import { ToolConfirmationPreview } from './ToolConfirmationPreview'
import { ToolStatusBadge } from './ToolStatusBadge'

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

  return <CandidatePanel
    title={result.fieldLabel || result.field}
    description={`${labels.relationCandidates} · ${result.relation}`}
    badge={result.query}
    emptyMessage={labels.relationNoResults}
    notice={stale ? <InlineNotice className="mt-3" tone="warning">{labels.relationSelectionExpired}</InlineNotice> : null}
    footer={multiple && result.candidates.length ? <div className="mt-3 flex items-center justify-between gap-3">
      <span className="text-[11px] text-muted">{labels.selectedRelationCount.replace('{count}', String(selected.length))}</span>
      <Button size="sm" variant="primary" className="h-8 rounded-md" disabled={stale || running || !selected.length} onClick={() => onSelect(tool, selected)}>{labels.confirmRelationSelection}</Button>
    </div> : null}
  >
    {result.candidates.map((candidate) => {
      const disabled = stale || running || !compatible(candidate)
      return multiple ? (
        <label key={candidate.id} className="flex min-h-9 items-center gap-2 rounded border border-border bg-background px-2.5 py-1.5 text-xs text-primary has-[:disabled]:opacity-45">
          <input type="checkbox" className="size-4" disabled={disabled} checked={selectedIds.includes(candidate.id)} onChange={() => toggle(candidate)} />
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
  const stale = result.snapshotId !== hostState.snapshotId || result.hostRevision !== hostState.hostRevision
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
    'odoo.open_x2many_record': '打开明细表单',
    'odoo.open_x2many_create': '新建明细表单',
    'odoo.prepare_x2many_import': '准备明细导入',
    'odoo.get_x2many_import_status': '查询导入状态',
    'odoo.reload_current_form': '重新载入表单',
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
        <ToolStatusBadge status={status} />
        {applied || rejected ? <span className="rounded-md bg-background px-2 py-1 text-[11px] text-muted">已应用 {applied} 项 / 已拒绝 {rejected} 项</span> : null}
      </summary>
      {tool.error || result.error ? <InlineNotice className="mt-2" tone="error">{String(tool.error || result.error)}</InlineNotice> : null}
      {status === 'needs_confirmation' || tool.needs_confirmation ? <div className="mt-2 rounded-md border border-solid border-warning/25 bg-warning/10 p-2 text-xs text-warning">
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

export function ToolCallCard({
  tool, renderers, onConfirm, onUndo, labels, hostState, running,
  onSelectRelation, onSelectRecord
}: ToolCallCardProps) {
  const Renderer = renderers?.[toolName(tool)]
  const fallback = <DefaultToolCallCard tool={tool} onConfirm={onConfirm} onUndo={onUndo} labels={labels} running={running} />
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
