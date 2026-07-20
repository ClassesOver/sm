import { Archive, Check, X } from 'lucide-react'
import type { SessionEntry } from '../types'
import { cn } from '../lib'
import { IconButton } from './IconButton'

interface SessionItemProps {
  session: SessionEntry
  selected: boolean
  confirmingArchive: boolean
  onLoad: (sessionId: string | number) => void
  onRequestArchive: (sessionId: string | number) => void
  onConfirmArchive: (sessionId: string | number) => void
  onCancelArchive: () => void
}

function formatSessionDate(value?: string | false): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric'
  })
}

export function SessionItem({
  session, selected, confirmingArchive,
  onLoad, onRequestArchive, onConfirmArchive, onCancelArchive
}: SessionItemProps) {
  const label = session.name || session.thread_id

  return <div className={cn(
    'group flex h-11 w-full items-center rounded-lg border border-solid transition-colors',
    selected ? 'border-primary/25 bg-accent' : 'border-transparent hover:bg-accent'
  )}>
    <button type="button"
      className={cn(
        'flex h-full min-w-0 flex-1 items-center justify-between gap-2 border-0 bg-transparent px-3 text-left text-sm',
        selected ? 'text-primary' : 'text-muted hover:text-primary'
      )}
      onClick={() => onLoad(session.id)}
    >
      <span className="min-w-0 truncate">{label}</span>
      <span className="shrink-0 text-[11px] text-muted">{formatSessionDate(session.write_date)}</span>
    </button>
    {confirmingArchive ? <>
      <IconButton label={`确认归档 ${label}`} title="确认归档" variant="danger" className="text-destructive" onClick={() => onConfirmArchive(session.id)}><Check className="size-3.5" /></IconButton>
      <IconButton label="取消归档" className="mr-1" onClick={onCancelArchive}><X className="size-3.5" /></IconButton>
    </> : <IconButton label={`归档 ${label}`} title="归档" variant="danger" className="mr-1 opacity-0 group-hover:opacity-100 focus:opacity-100" onClick={() => onRequestArchive(session.id)}><Archive className="size-3.5" /></IconButton>}
  </div>
}
