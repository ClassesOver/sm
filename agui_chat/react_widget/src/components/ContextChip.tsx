import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../lib'
import { IconButton } from './IconButton'

interface ContextChipProps {
  icon: ReactNode
  label: string
  title?: string
  tone?: 'neutral' | 'accent' | 'positive' | 'warning'
  trailing?: ReactNode
  onRemove?: () => void
  removeLabel?: string
  removeTitle?: string
  className?: string
}

export function ContextChip({
  icon,
  label,
  title,
  tone = 'neutral',
  trailing,
  onRemove,
  removeLabel = `移除 ${label}`,
  removeTitle = removeLabel,
  className
}: ContextChipProps) {
  return <span className={cn(
    'inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
    tone === 'neutral' && 'border-border bg-background-panel text-primary',
    tone === 'accent' && 'border-primary/20 bg-accent text-primary',
    tone === 'positive' && 'border-positive/25 bg-positive/10 text-positive',
    tone === 'warning' && 'border-warning/35 bg-warning/10 text-warning',
    className
  )} title={title}>
    <span className="flex shrink-0 items-center">{icon}</span>
    <span className="truncate">{label}</span>
    {trailing}
    {onRemove ? <IconButton
      label={removeLabel}
      title={removeTitle}
      size="xs"
      className="size-5 rounded text-current opacity-65 hover:bg-background hover:text-current hover:opacity-100"
      onClick={onRemove}
    >
      <X size={12} />
    </IconButton> : null}
  </span>
}
