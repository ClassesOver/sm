import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib'

interface InlineNoticeProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role'> {
  tone?: 'error' | 'warning' | 'info'
  variant?: 'card' | 'band'
  role?: 'alert' | 'status'
  action?: ReactNode
}

export function InlineNotice({
  tone = 'info',
  variant = 'card',
  role = tone === 'error' ? 'alert' : 'status',
  action,
  className,
  children,
  ...props
}: InlineNoticeProps) {
  return <div role={role} className={cn(
    'flex items-center gap-2 text-xs',
    variant === 'card' && 'rounded border p-2',
    variant === 'band' && 'border-b px-3 py-2',
    tone === 'error' && 'border-destructive/25 bg-destructive/10 text-destructive',
    tone === 'warning' && 'border-warning/30 bg-warning/10 text-warning',
    tone === 'info' && 'border-primary/20 bg-accent text-secondary',
    className
  )} {...props}>
    <span className="min-w-0 flex-1">{children}</span>
    {action}
  </div>
}
