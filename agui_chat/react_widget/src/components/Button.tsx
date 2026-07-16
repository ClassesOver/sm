import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost' | 'subtle' | 'danger'
  size?: 'sm' | 'md' | 'icon'
  children: ReactNode
}

export function Button({
  className,
  variant = 'subtle',
  size = 'md',
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg border border-solid transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        size === 'sm' && 'h-8 px-2.5 text-xs',
        size === 'md' && 'h-9 px-3 text-sm',
        size === 'icon' && 'size-9 p-0',
        variant === 'primary' &&
          'border-primary bg-primary text-primaryAccent hover:bg-primary/85',
        variant === 'subtle' &&
          'border-border bg-accent text-primary hover:bg-background-secondary',
        variant === 'ghost' &&
          'border-transparent bg-transparent text-muted hover:bg-accent hover:text-primary',
        variant === 'danger' &&
          'border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20',
        className
      )}
      {...props}
    >
      {children}
    </button>
  )
}
