import { useEffect, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type {
  ChatLabels, OdooHostSnapshot, RecordCandidate, RelationCandidate, ToolCall, ToolRenderer
} from '../types'
import type { ToolCallGroupPresentation } from './messagePresentation'
import { getToolEffectiveStatus } from './messagePresentation'
import { ToolCallRow } from './ToolCallCard'
import { ToolStatusBadge } from './ToolStatusBadge'

interface ToolCallGroupProps {
  group: ToolCallGroupPresentation
  renderers?: Record<string, ToolRenderer>
  labels: ChatLabels
  hostState: OdooHostSnapshot
  running: boolean
  onSelectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => void
  onSelectRecord: (tool: ToolCall, candidate: RecordCandidate) => void
  onConfirmTool: (tool: ToolCall, approved: boolean) => void
  onUndoTool: (tool: ToolCall) => void
}

const GROUP_STATUS_LABELS: Record<ToolCallGroupPresentation['status'], string> = {
  needs_confirmation: '待确认',
  needs_selection: '待选择',
  running: '执行中',
  error: '有失败',
  cancelled: '已取消',
  ok: '已完成'
}

function scrollToActive(container: HTMLDivElement, activeIndex: number): void {
  if (activeIndex < 0) return
  const row = container.children.item(activeIndex) as HTMLElement | null
  if (!row) return
  const viewTop = container.scrollTop
  const viewBottom = viewTop + container.clientHeight
  const containerRect = container.getBoundingClientRect()
  const rowRect = row.getBoundingClientRect()
  const rowTop = rowRect.top - containerRect.top + viewTop
  const rowBottom = rowTop + rowRect.height
  let nextTop: number | null = null
  if (rowBottom > viewBottom) nextTop = rowBottom - container.clientHeight
  if (rowTop < viewTop) nextTop = rowTop
  if (nextTop === null) return
  const maxTop = Math.max(0, container.scrollHeight - container.clientHeight)
  const top = Math.max(0, Math.min(nextTop, maxTop))
  const prefersReducedMotion = typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (typeof container.scrollTo === 'function') {
    container.scrollTo({ top, behavior: prefersReducedMotion ? 'auto' : 'smooth' })
  } else {
    container.scrollTop = top
  }
}

export function ToolCallGroup({
  group, renderers, labels, hostState, running, onSelectRelation, onSelectRecord,
  onConfirmTool, onUndoTool
}: ToolCallGroupProps) {
  const [open, setOpen] = useState(group.requiresAttention)
  const previousAttention = useRef(group.requiresAttention)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (group.requiresAttention !== previousAttention.current) setOpen(group.requiresAttention)
    previousAttention.current = group.requiresAttention
  }, [group.requiresAttention])

  useEffect(() => {
    if (!open || !group.requiresAttention || !listRef.current) return
    scrollToActive(listRef.current, group.activeToolIndex)
  }, [open, group.activeToolIndex, group.requiresAttention, group.status, group.tools.length])

  const summaryLabel = `思考过程，${group.tools.length} 个工具，${GROUP_STATUS_LABELS[group.status]}`
  return <details
    open={open}
    className="agui-tool-group min-w-0"
    data-testid="tool-call-group"
    aria-label={summaryLabel}
    onToggle={(event) => setOpen(event.currentTarget.open)}
  >
    <summary className="flex min-h-8 cursor-pointer list-none items-center gap-2 rounded-md px-1 py-1 text-xs text-muted outline-none transition-colors hover:bg-background-secondary/70 focus-visible:bg-background-secondary/70">
      <ChevronRight className="agui-tool-group-chevron size-3.5 shrink-0 transition-transform" aria-hidden="true" />
      <span className="shrink-0 font-medium text-secondary">思考过程</span>
      <span className="shrink-0 text-[11px]">· {group.tools.length} 个工具</span>
      <ToolStatusBadge status={group.status} />
    </summary>
    <div ref={listRef} role="list" className="agui-tool-group-list mt-1 max-h-56 overflow-y-auto border-l border-border/70 pl-2">
      {group.tools.map((tool, index) => <ToolCallRow
        key={tool.key || tool.id || `${group.key}-${index}`}
        tool={tool}
        effectiveStatus={getToolEffectiveStatus(tool)}
        renderers={renderers}
        labels={labels}
        hostState={hostState}
        running={running}
        onSelectRelation={onSelectRelation}
        onSelectRecord={onSelectRecord}
        onConfirm={(approved) => onConfirmTool(tool, approved)}
        onUndo={() => onUndoTool(tool)}
      />)}
    </div>
  </details>
}
