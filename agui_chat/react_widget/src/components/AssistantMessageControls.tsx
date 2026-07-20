import type { ChatIcons, ChatLabels } from '../types'
import { cn } from '../lib'
import { IconButton } from './IconButton'
import { useCopyFeedback } from './useCopyFeedback'

interface AssistantMessageControlsProps {
  isCurrent: boolean
  running: boolean
  canRegenerate: boolean
  labels: ChatLabels
  icons: ChatIcons
  onCopy: () => Promise<void> | void
  onRegenerate: () => void
}

export function AssistantMessageControls({
  isCurrent, running, canRegenerate, labels, icons, onCopy, onRegenerate
}: AssistantMessageControlsProps) {
  const { copied, copy } = useCopyFeedback(onCopy)

  return <div className={cn(
    'agui-message-controls mt-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100',
    isCurrent && 'opacity-100'
  )}>
    <IconButton label={copied ? labels.copied : labels.copyResponse} title={labels.copyResponse} className="rounded" onClick={() => void copy()}>{copied ? icons.complete : icons.copy}</IconButton>
    <IconButton label={labels.regenerateResponse} className="rounded" disabled={running || !canRegenerate} onClick={onRegenerate}>{icons.regenerate}</IconButton>
  </div>
}
