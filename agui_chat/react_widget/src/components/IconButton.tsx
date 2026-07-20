import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib'

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'children'> {
  label: string
  size?: 'xs' | 'sm' | 'md'
  variant?: 'ghost' | 'soft' | 'outline' | 'danger'
  children: ReactNode
}

export function IconButton({
  label,
  title = label,
  size = 'sm',
  variant = 'ghost',
  className,
  children,
  ...props
}: IconButtonProps) {
  return <button
    type="button"
    aria-label={label}
    title={title}
    className={cn(
      'grid shrink-0 place-items-center rounded-md border transition-colors disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/35',
      size === 'xs' && 'size-6',
      size === 'sm' && 'size-7',
      size === 'md' && 'size-8',
      variant === 'ghost' && 'border-transparent bg-transparent text-muted hover:bg-accent hover:text-primary',
      variant === 'soft' && 'border-transparent bg-background-secondary text-secondary hover:bg-accent hover:text-primary',
      variant === 'outline' && 'border-border bg-background-panel text-muted hover:bg-accent hover:text-primary',
      variant === 'danger' && 'border-transparent bg-transparent text-muted hover:bg-destructive/10 hover:text-destructive',
      className
    )}
    {...props}
  >
    {children}
  </button>
}
