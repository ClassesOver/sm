import { Children } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib'

interface CandidatePanelProps {
  title: string
  description: string
  badge: ReactNode
  emptyMessage: string
  notice?: ReactNode
  footer?: ReactNode
  children?: ReactNode
}

export function CandidatePanel({
  title, description, badge, emptyMessage, notice, footer, children
}: CandidatePanelProps) {
  const hasOptions = Children.count(children) > 0
  return <div className="rounded-lg border border-border bg-background-secondary/80 p-3">
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="truncate text-xs font-semibold text-primary">{title}</div>
        <div className="mt-0.5 truncate text-[11px] text-muted">{description}</div>
      </div>
      <span className="shrink-0 rounded border border-border bg-background px-2 py-1 text-[10px] text-muted">{badge}</span>
    </div>
    {notice}
    {hasOptions ? <div className="mt-3 grid gap-1.5">{children}</div> : <div className="mt-3 text-xs text-muted">{emptyMessage}</div>}
    {footer}
  </div>
}

interface CandidateOptionProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  trailing?: ReactNode
}

export function CandidateOption({ children, trailing, className, ...props }: CandidateOptionProps) {
  return <button
    type="button"
    className={cn(
      'flex min-h-9 items-center gap-2 rounded border border-solid border-border bg-background px-2.5 py-1.5 text-left text-xs text-primary hover:bg-accent disabled:opacity-45',
      className
    )}
    {...props}
  >
    <span className="min-w-0 flex-1 truncate">{children}</span>
    {trailing}
  </button>
}
