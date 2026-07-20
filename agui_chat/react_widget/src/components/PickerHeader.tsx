import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'

interface PickerHeaderProps {
  title: string
  leading?: ReactNode
  onBack?: () => void
}

export function PickerHeader({ title, leading, onBack }: PickerHeaderProps) {
  return <div className="flex h-9 items-center gap-2 border-b border-border px-2">
    {onBack ? <button
      type="button"
      className="grid size-7 place-items-center rounded-md border-0 bg-background-secondary text-secondary shadow-none transition-colors hover:bg-accent hover:text-primary"
      aria-label="返回"
      onClick={onBack}
    >
      <ArrowLeft size={15} />
    </button> : leading ? <span className="grid size-7 shrink-0 place-items-center text-muted">{leading}</span> : null}
    <span className="min-w-0 flex-1 truncate text-xs font-medium">{title}</span>
  </div>
}
