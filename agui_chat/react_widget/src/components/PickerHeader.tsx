import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { IconButton } from './IconButton'

interface PickerHeaderProps {
  title: string
  leading?: ReactNode
  onBack?: () => void
}

export function PickerHeader({ title, leading, onBack }: PickerHeaderProps) {
  return <div className="flex h-9 items-center gap-2 border-b border-border px-2">
    {onBack ? <IconButton label="返回" variant="soft" onClick={onBack}>
      <ArrowLeft size={15} />
    </IconButton> : leading ? <span className="grid size-7 shrink-0 place-items-center text-muted">{leading}</span> : null}
    <span className="min-w-0 flex-1 truncate text-xs font-medium">{title}</span>
  </div>
}
