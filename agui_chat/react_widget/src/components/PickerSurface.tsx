import { forwardRef } from 'react'
import type { HTMLAttributes } from 'react'
import { cn } from '../lib'

interface PickerSurfaceProps extends Omit<HTMLAttributes<HTMLDivElement>, 'aria-label' | 'role'> {
  ariaLabel: string
}

export const PickerSurface = forwardRef<HTMLDivElement, PickerSurfaceProps>(function PickerSurface({
  ariaLabel, className, children, ...props
}, ref) {
  return <div
    ref={ref}
    className={cn(
      'agui-picker absolute bottom-full left-0 z-40 mb-2 w-full max-w-md overflow-hidden rounded-md border border-border/70 bg-white text-primary shadow-[0_12px_32px_rgba(15,23,42,0.14)]',
      className
    )}
    role="dialog"
    aria-label={ariaLabel}
    {...props}
  >
    {children}
  </div>
})
