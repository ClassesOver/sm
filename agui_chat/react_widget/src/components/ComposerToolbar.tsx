import { FolderOpen, Sparkles } from 'lucide-react'
import type { ChatIcons, ChatLabels } from '../types'
import { cn } from '../lib'
import { Button } from './Button'

interface ComposerToolbarProps {
  attachmentsEnabled: boolean
  skillsEnabled: boolean
  disabled: boolean
  sending: boolean
  running: boolean
  canSend: boolean
  skillOpen: boolean
  labels: ChatLabels
  icons: ChatIcons
  onAddAttachments: () => void
  onToggleSkills: () => void
  onOpenWorkspace?: () => void
  onStop: () => void
}

export function ComposerToolbar({
  attachmentsEnabled, skillsEnabled, disabled, sending, running, canSend, skillOpen,
  labels, icons, onAddAttachments, onToggleSkills, onOpenWorkspace, onStop
}: ComposerToolbarProps) {
  return <div className="mt-2 flex min-h-8 items-center justify-between gap-2">
    <div className="flex items-center gap-1">
      {attachmentsEnabled ? <Button type="button" variant="ghost" size="icon" disabled={disabled} className="size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:border-primary/20 hover:bg-accent" aria-label={labels.addAttachments} title={labels.addAttachments} onClick={onAddAttachments}>
        {icons.upload}
      </Button> : null}
      {skillsEnabled ? <Button type="button" variant="ghost" size="icon" disabled={disabled || sending} className={cn('size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:bg-accent', skillOpen && 'bg-accent text-primary')} aria-label="选择技能" title="选择技能" aria-pressed={skillOpen} onClick={onToggleSkills}>
        <Sparkles className="size-4" />
      </Button> : null}
      {onOpenWorkspace ? <Button type="button" variant="ghost" size="icon" disabled={disabled} className="size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:bg-accent" aria-label="打开工作区" title="打开工作区" onClick={onOpenWorkspace}>
        <FolderOpen className="size-4" />
      </Button> : null}
    </div>
    <Button type={running ? 'button' : 'submit'} variant="primary" size="icon" className={cn('size-8 shrink-0 rounded-md shadow-none disabled:border-border disabled:bg-border disabled:text-muted', running && 'ring-1 ring-primary/15')} disabled={running ? false : disabled || !canSend} aria-label={running ? labels.stopGenerating : labels.sendMessage} title={running ? labels.stopGenerating : labels.sendMessage} onClick={running ? onStop : undefined}>
      {running ? icons.stop : icons.send}
    </Button>
  </div>
}
