import { Search } from 'lucide-react'
import type { InputHTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib'

interface PickerSearchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  trailing?: ReactNode
  containerClassName?: string
}

export function PickerSearch({
  trailing, containerClassName, className, ...inputProps
}: PickerSearchProps) {
  return <div className={cn(
    'sticky top-0 z-10 flex min-h-12 items-center gap-2 border-b border-border/60 bg-white px-2 py-2',
    containerClassName
  )}>
    <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-background-secondary shadow-[inset_0_1px_2px_rgba(15,23,42,0.04)] px-2.5 transition-colors focus-within:border-primary/35 focus-within:bg-white focus-within:outline focus-within:outline-1 focus-within:outline-primary/15 focus-within:shadow-[0_0_0_3px_rgba(59,130,246,0.07)]">
      <Search size={14} className="shrink-0 text-muted" />
      <input
        {...inputProps}
        className={cn(
          'min-w-0 flex-1 border-0 bg-transparent text-xs text-primary outline-none placeholder:text-muted',
          className
        )}
      />
    </label>
    {trailing ? <span className="shrink-0 text-[10px] text-muted">{trailing}</span> : null}
  </div>
}
