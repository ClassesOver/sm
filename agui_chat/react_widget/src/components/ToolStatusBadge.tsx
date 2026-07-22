import { CheckCircle2, CircleAlert, Clock3, ListChecks, Loader2 } from 'lucide-react'
import type { ToolStatus } from '../types'
import { cn } from '../lib'

interface ToolStatusBadgeProps {
  status?: ToolStatus | 'needs_selection'
}

function statusClass(status?: ToolStatus | 'needs_selection'): string {
  if (status === 'ok') return 'border-positive/30 bg-positive/10 text-positive'
  if (status === 'error' || status === 'cancelled') return 'border-destructive/35 bg-destructive/10 text-destructive'
  if (status === 'needs_confirmation') return 'border-warning/35 bg-warning/10 text-warning'
  return 'border-primary/15 bg-accent text-muted'
}

function statusIcon(status?: ToolStatus | 'needs_selection') {
  if (status === 'running') return <Loader2 className="size-3 animate-spin" />
  if (status === 'ok') return <CheckCircle2 className="size-3" />
  if (status === 'error' || status === 'cancelled') return <CircleAlert className="size-3" />
  if (status === 'needs_selection') return <ListChecks className="size-3" />
  return <Clock3 className="size-3" />
}

function statusLabel(status?: ToolStatus | 'needs_selection'): string {
  if (status === 'running') return '执行中'
  if (status === 'ok') return '已完成'
  if (status === 'error') return '出错'
  if (status === 'cancelled') return '已取消'
  if (status === 'needs_confirmation') return '待确认'
  if (status === 'needs_selection') return '待选择'
  return '等待中'
}

export function ToolStatusBadge({ status }: ToolStatusBadgeProps) {
  return <span className={cn('inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] uppercase', statusClass(status))}>
    {statusIcon(status)}{statusLabel(status)}
  </span>
}
