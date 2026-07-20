import { UploadCloud } from 'lucide-react'
import { FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type {
  AgentSkillOption, AttachmentOptions, AttachmentRef, ChatIcons, ChatLabels, HostBridge,
  MenuMention, MenuMentionOption, MentionReference, SelectedAgentSkill, WorkspaceReference
} from '../types'
import { AttachmentQueue } from './AttachmentQueue'
import { ComposerContextBar } from './ComposerContextBar'
import { ComposerToolbar } from './ComposerToolbar'
import { MentionPicker, type MentionPickerHandle } from './MentionPicker'
import { SkillPicker, type SkillPickerHandle } from './SkillPicker'
import { useComposerAttachments } from './useComposerAttachments'
import { useComposerQueryState } from './useComposerQueryState'

export { menuQueryAtCursor } from './useComposerQueryState'

export interface ChatInputProps {
  running: boolean
  disabled?: boolean
  attachments?: boolean | AttachmentOptions
  menuOptions: MenuMentionOption[]
  agentSkills?: AgentSkillOption[]
  hostBridge?: HostBridge
  workspaceReferences?: WorkspaceReference[]
  onRemoveWorkspaceReference?: (id: string) => void
  onSend: (
    content: string,
    attachments: AttachmentRef[],
    mentions?: MentionReference[] | MenuMention,
    skills?: SelectedAgentSkill[],
    workspaceReferences?: WorkspaceReference[]
  ) => Promise<boolean | void> | boolean | void
  onStop: () => void
  onUpload: (file: File, onProgress: (progress: number) => void) => Promise<AttachmentRef>
  onRemove: (attachmentId: string) => Promise<void>
  labels: ChatLabels
  icons: ChatIcons
  onOpenWorkspace?: () => void
}

export function ChatInput({
  running, disabled = false, attachments, menuOptions, agentSkills = [],
  onSend, onStop, onUpload, onRemove, labels, icons, onOpenWorkspace, workspaceReferences = [], onRemoveWorkspaceReference
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const [menuMention, setMenuMention] = useState<MenuMention | undefined>()
  const [selectedSkills, setSelectedSkills] = useState<SelectedAgentSkill[]>([])
  const [sending, setSending] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const formRef = useRef<HTMLFormElement | null>(null)
  const mentionPickerRef = useRef<MentionPickerHandle | null>(null)
  const skillPickerRef = useRef<SkillPickerHandle | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const picker = useComposerQueryState({
    value,
    setValue,
    hasSkills: agentSkills.length > 0,
    textareaRef
  })
  const attachmentState = useComposerAttachments({
    attachments,
    disabled,
    textareaRef,
    onUpload,
    onRemove
  })
  useEffect(() => {
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      const form = formRef.current
      const insideForm = Boolean(form && (
        form.contains(event.target as Node) || event.composedPath().includes(form)
      ))
      if (!insideForm) {
        picker.dismissPickers()
      }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('focusin', closeOutside)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('focusin', closeOutside)
    }
  }, [picker.dismissPickers])

  useEffect(() => {
    setSelectedSkills((current) => {
      const next = current.map((skill) => ({ ...skill, valid: agentSkills.some((option) => option.id === skill.id && option.name === skill.name) }))
      return next.every((skill, index) => skill.valid === current[index].valid) ? current : next
    })
  }, [agentSkills])
  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    const style = window.getComputedStyle(textarea)
    const lineHeight = Number.parseFloat(style.lineHeight) || 20
    const maxHeight = lineHeight * 6 + Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom)
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [value])

  const canSend = !running && !sending && !disabled && !attachmentState.items.some((item) => item.status !== 'ready') &&
    (!!value.trim() || attachmentState.readyAttachments.length > 0 || !!menuMention || selectedSkills.length > 0 || workspaceReferences.length > 0)

  const selectMenu = (option: MenuMentionOption) => {
    const query = picker.consumeMenuQuery()
    if (!query) return
    setMenuMention({ ...option, path: [...option.path], valid: true })
  }

  const toggleSkill = (skill: AgentSkillOption) => {
    setSelectedSkills((current) => {
      if (current.some((item) => item.id === skill.id)) {
        return current.filter((item) => item.id !== skill.id)
      }
      return [{ ...skill, valid: true }]
    })
    picker.completeSkillSelection()
  }

  const submit = async () => {
    if (!canSend) return
    const content = value.trim()
    setSending(true)
    let sent: boolean | void = false
    try {
      sent = await Promise.resolve(selectedSkills.length
        ? onSend(
            content,
            attachmentState.readyAttachments,
            menuMention,
            selectedSkills.map((skill) => ({ ...skill })),
            workspaceReferences.map((reference) => ({ ...reference }))
          )
        : onSend(content, attachmentState.readyAttachments, menuMention, undefined, workspaceReferences.map((reference) => ({ ...reference }))))
    } catch (_error) {
      sent = false
    } finally {
      setSending(false)
    }
    if (sent === false) return
    setValue('')
    setMenuMention(undefined)
    setSelectedSkills([])
    picker.dismissPickers()
    attachmentState.resetItems()
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (picker.skillOpen && skillPickerRef.current?.handleKey(event)) return
    if (picker.menuQuery && mentionPickerRef.current?.handleKey(event)) return
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <form ref={formRef}
      className="relative w-full shrink-0 border border-solid border-border/60 bg-background-panel px-4 pb-3 pt-3 shadow-none sm:px-6"
      onClick={(event) => {
        const target = event.target as HTMLElement
        if (!target.closest('button, a, input, textarea')) textareaRef.current?.focus()
      }}
      onSubmit={(event: FormEvent) => { event.preventDefault(); void submit() }}
    >
      {attachmentState.dragging && textareaRef.current?.closest('main') ? createPortal(
        <div className="pointer-events-none absolute inset-0 z-50 grid place-items-center border-2 border-dashed border-primary/30 bg-background-panel/95 text-secondary backdrop-blur-[1px]" aria-label="拖放附件">
          <UploadCloud className="size-6" />
        </div>,
        textareaRef.current.closest('main') as Element
      ) : null}
      <AttachmentQueue
        items={attachmentState.items}
        labels={labels}
        onClear={attachmentState.clearItems}
        onRemove={attachmentState.removeItem}
      />
      <div>
        <ComposerContextBar
          workspaceReferences={workspaceReferences}
          selectedSkills={selectedSkills}
          menuMention={menuMention}
          onRemoveWorkspaceReference={onRemoveWorkspaceReference}
          onRemoveSkill={(id) => setSelectedSkills((current) => current.filter((item) => item.id !== id))}
          onRemoveMenuMention={() => setMenuMention(undefined)}
        />
        <div className="relative">
          <textarea ref={textareaRef} rows={1} disabled={disabled || sending} className="block min-h-11 w-full resize-none rounded-lg border-0 bg-background-secondary px-3 py-3 text-sm leading-5 text-primary outline outline-1 outline-transparent transition-[border-color,background-color,outline-color,box-shadow] placeholder:text-muted/90 focus:bg-background focus:outline-primary/15 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.06)] disabled:cursor-not-allowed disabled:opacity-45" placeholder={labels.inputPlaceholder} value={value} onChange={(event) => {
            const nextValue = event.target.value
            const cursor = event.target.selectionStart ?? nextValue.length
            picker.handleValueChange(nextValue, cursor)
          }} onClick={(event) => {
            const cursor = event.currentTarget.selectionStart ?? value.length
            picker.handleCursorChange(cursor)
          }} onKeyDown={onKeyDown} onPasteCapture={attachmentState.handlePaste} aria-autocomplete="list" aria-expanded={Boolean(picker.menuQuery || picker.skillOpen)} aria-controls={picker.skillOpen ? 'agui-skill-options' : picker.menuQuery ? 'agui-mention-options' : undefined} />
          {picker.mentionPickerQuery ? <MentionPicker ref={mentionPickerRef} open={Boolean(picker.menuQuery)} query={picker.mentionPickerQuery} menuOptions={menuOptions} onSelectMenu={selectMenu} onOpenSkills={picker.openSkillsFromMention} onFocusInput={() => textareaRef.current?.focus({ preventScroll: true })} onClose={picker.closeMenuPicker} /> : null}
          <SkillPicker ref={skillPickerRef} open={picker.skillOpen} query={picker.skillSearch} skills={agentSkills} selected={selectedSkills} inlineQuery={Boolean(picker.mentionSkillQuery)} onQueryChange={picker.setSkillSearch} onToggle={toggleSkill} onBack={picker.skillReturnQuery ? picker.returnToMentionCategories : undefined} onClose={picker.closeSkillPicker} />
        </div>
        {attachmentState.enabled ? <input ref={inputRef} className="hidden" type="file" disabled={disabled} multiple accept={attachmentState.acceptedFileSelector} onChange={(event) => {
          attachmentState.addFiles(Array.from(event.target.files || []))
          event.target.value = ''
        }} /> : null}
        <ComposerToolbar
          attachmentsEnabled={attachmentState.enabled}
          skillsEnabled={agentSkills.length > 0}
          disabled={disabled}
          sending={sending}
          running={running}
          canSend={canSend}
          skillOpen={picker.skillOpen}
          labels={labels}
          icons={icons}
          onAddAttachments={() => inputRef.current?.click()}
          onToggleSkills={picker.toggleSkillPicker}
          onOpenWorkspace={onOpenWorkspace}
          onStop={onStop}
        />
      </div>
    </form>
  )
}
