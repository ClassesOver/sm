import { AtSign, FileText, Folder, FolderOpen, Sparkles, UploadCloud, X } from 'lucide-react'
import { ClipboardEvent, FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type {
  AgentSkillOption, AttachmentOptions, AttachmentRef, ChatIcons, ChatLabels, HostBridge,
  MenuMention, MenuMentionOption, MentionReference, SelectedAgentSkill, WorkspaceReference
} from '../types'
import { cn } from '../lib'
import { Button } from './Button'
import { MentionPicker, type MentionPickerHandle, type MentionQuery } from './MentionPicker'
import {
  SkillPicker, type SkillPickerHandle, type SkillQuery, skillQueryAtCursor
} from './SkillPicker'

const ACCEPTED_TYPES: Record<string, 'image' | 'document'> = {
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/webp': 'image',
  'application/pdf': 'document',
  'text/plain': 'document',
  'text/csv': 'document',
  'application/csv': 'document',
  'application/json': 'document',
  'application/jsonl': 'document',
  'application/x-ndjson': 'document',
  'application/vnd.ms-excel': 'document',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'document'
}
const REPORT_EXTENSIONS = new Set(['csv', 'xlsx', 'json', 'jsonl'])
const ACCEPTED_FILE_SELECTOR = [...Object.keys(ACCEPTED_TYPES), ...[...REPORT_EXTENSIONS].map((value) => `.${value}`)].join(',')
const MB = 1024 * 1024

interface UploadItem {
  localId: string
  file: File
  progress: number
  status: 'uploading' | 'ready' | 'error'
  attachment?: AttachmentRef
  previewUrl?: string
  error?: string
}

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

const MENTION_BOUNDARY = /[\s,，.。!！?？;；:：、()\[\]{}【】<>《》"'“”‘’]/u
const MENTION_TERMINATOR = /[\s@,，.。!！?？;；:：、()\[\]{}【】<>《》"'“”‘’]/u

export function menuQueryAtCursor(value: string, cursor: number): MentionQuery | null {
  const safeCursor = Math.max(0, Math.min(cursor, value.length))
  let at = safeCursor - 1
  while (at >= 0 && value[at] !== '@' && !MENTION_TERMINATOR.test(value[at])) at -= 1
  if (at < 0 || value[at] !== '@') return null
  if (at > 0 && !MENTION_BOUNDARY.test(value[at - 1])) return null
  let end = safeCursor
  while (end < value.length && !MENTION_TERMINATOR.test(value[end])) end += 1
  return { start: at, end, query: value.slice(at + 1, end) }
}

function formatSize(size: number): string {
  return size < MB ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / MB).toFixed(1)} MB`
}

function fileBadge(file: File): string {
  const extension = file.name.split('.').pop()?.toUpperCase()
  return extension && extension.length <= 4 ? extension : '文件'
}

function uploadedLabel(template: string, count: number): string {
  return template.replace('{count}', String(count))
}

function acceptedModality(file: File): 'image' | 'document' | undefined {
  const extension = file.name.split('.').pop()?.toLocaleLowerCase() || ''
  return ACCEPTED_TYPES[file.type] || (REPORT_EXTENSIONS.has(extension) ? 'document' : undefined)
}

function fileKind(file: File): string {
  if (file.type === 'application/pdf') return 'PDF 文档'
  if (file.type.includes('spreadsheet') || file.type.includes('excel') || file.type === 'text/csv') return 'Excel 表格'
  if (file.type.includes('word')) return 'Word 文档'
  if (file.type.startsWith('image/')) return '图片'
  if (file.type.startsWith('text/')) return '文本文件'
  return '文档'
}

export function ChatInput({
  running, disabled = false, attachments, menuOptions, agentSkills = [],
  onSend, onStop, onUpload, onRemove, labels, icons, onOpenWorkspace, workspaceReferences = [], onRemoveWorkspaceReference
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const [menuMention, setMenuMention] = useState<MenuMention | undefined>()
  const [menuQuery, setMenuQuery] = useState<MentionQuery | null>(null)
  const [selectedSkills, setSelectedSkills] = useState<SelectedAgentSkill[]>([])
  const [skillQuery, setSkillQuery] = useState<SkillQuery | null>(null)
  const [skillSearch, setSkillSearch] = useState('')
  const [skillOpen, setSkillOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [items, setItems] = useState<UploadItem[]>([])
  const [dragging, setDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const formRef = useRef<HTMLFormElement | null>(null)
  const mentionPickerRef = useRef<MentionPickerHandle | null>(null)
  const skillPickerRef = useRef<SkillPickerHandle | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragDepth = useRef(0)
  const config = typeof attachments === 'object' ? attachments : {}
  const enabled = attachments !== false && config.enabled !== false
  const maxFileSize = config.maxFileSize || 10 * MB
  const maxFiles = config.maxFiles || 5
  const maxTotalSize = config.maxTotalSize || 25 * MB
  useEffect(() => {
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      const form = formRef.current
      const insideForm = Boolean(form && (
        form.contains(event.target as Node) || event.composedPath().includes(form)
      ))
      if (!insideForm) {
        setMenuQuery(null)
        setSkillOpen(false)
      }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('focusin', closeOutside)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('focusin', closeOutside)
    }
  }, [])

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

  const updateItem = (localId: string, values: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => item.localId === localId ? { ...item, ...values } : item))
  }

  const addFiles = (files: File[]) => {
    if (!enabled || disabled || !files.length) return
    const next: UploadItem[] = []
    let count = items.length
    let totalSize = items.reduce((sum, item) => sum + item.file.size, 0)
    files.forEach((file) => {
      let error = ''
      const modality = acceptedModality(file)
      if (!modality) error = '不支持的文件类型'
      else if (file.size > maxFileSize) error = `文件超过 ${formatSize(maxFileSize)}`
      else if (count >= maxFiles) error = `最多添加 ${maxFiles} 个文件`
      else if (totalSize + file.size > maxTotalSize) error = `附件总大小超过 ${formatSize(maxTotalSize)}`
      const localId = `${Date.now()}-${Math.random()}`
      next.push({
        localId,
        file,
        progress: 0,
        status: error ? 'error' : 'uploading',
        error: error || undefined,
        previewUrl: modality === 'image' ? URL.createObjectURL(file) : undefined
      })
      count += 1
      totalSize += file.size
    })
    setItems((current) => [...current, ...next])
    next.filter((item) => item.status === 'uploading').forEach((item) => {
      void onUpload(item.file, (progress) => updateItem(item.localId, { progress })).then(
        (attachment) => updateItem(item.localId, { attachment, progress: 100, status: 'ready' }),
        (error) => updateItem(item.localId, { error: (error as Error)?.message || '上传失败', status: 'error' })
      )
    })
  }

  useEffect(() => {
    if (!enabled || disabled) return
    const dropRegion = textareaRef.current?.closest('main')
    if (!dropRegion) return
    const hasFiles = (transfer: DataTransfer | null) => Boolean(transfer && (
      transfer.files.length ||
      Array.from(transfer.types || []).some((type) => String(type).toLocaleLowerCase() === 'files') ||
      Array.from(transfer.items || []).some((item) => item.kind === 'file')
    ))
    const filesFrom = (transfer: DataTransfer | null): File[] => {
      if (!transfer) return []
      const files = Array.from(transfer.files || [])
      Array.from(transfer.items || []).forEach((item) => {
        if (item.kind !== 'file') return
        const file = item.getAsFile()
        if (file && !files.includes(file)) files.push(file)
      })
      return files
    }
    const dragEnter = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      if (!hasFiles(event.dataTransfer)) return
      event.preventDefault()
      dragDepth.current += 1
      setDragging(true)
    }
    const dragOver = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      if (hasFiles(event.dataTransfer)) event.preventDefault()
    }
    const dragLeave = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      if (dragDepth.current === 0) return
      event.preventDefault()
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setDragging(false)
    }
    const drop = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      const files = filesFrom(event.dataTransfer)
      dragDepth.current = 0
      setDragging(false)
      if (!files.length) return
      event.preventDefault()
      addFiles(files)
    }
    dropRegion.addEventListener('dragenter', dragEnter)
    dropRegion.addEventListener('dragover', dragOver)
    dropRegion.addEventListener('dragleave', dragLeave)
    dropRegion.addEventListener('drop', drop)
    return () => {
      dropRegion.removeEventListener('dragenter', dragEnter)
      dropRegion.removeEventListener('dragover', dragOver)
      dropRegion.removeEventListener('dragleave', dragLeave)
      dropRegion.removeEventListener('drop', drop)
    }
  }, [disabled, enabled, items])

  const removeItem = (item: UploadItem) => {
    setItems((current) => current.filter((candidate) => candidate.localId !== item.localId))
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    if (item.attachment) void onRemove(item.attachment.id)
  }

  const readyAttachments = items.flatMap((item) => item.attachment ? [item.attachment] : [])
  const canSend = !running && !sending && !disabled && !items.some((item) => item.status !== 'ready') &&
    (!!value.trim() || readyAttachments.length > 0 || !!menuMention || selectedSkills.length > 0 || workspaceReferences.length > 0)
  const mentionSkillQuery = skillOpen && skillQuery && value[skillQuery.start] === '@' ? skillQuery : null

  const selectMenu = (option: MenuMentionOption) => {
    if (!menuQuery) return
    const cursor = menuQuery.start
    setValue((current) => current.slice(0, menuQuery.start) + current.slice(menuQuery.end))
    setMenuMention({ ...option, path: [...option.path], valid: true })
    setMenuQuery(null)
    window.setTimeout(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(cursor, cursor)
    }, 0)
  }

  const toggleSkill = (skill: AgentSkillOption) => {
    setSelectedSkills((current) => {
      if (current.some((item) => item.id === skill.id)) {
        return current.filter((item) => item.id !== skill.id)
      }
      return [{ ...skill, valid: true }]
    })
    setSkillOpen(false)
    if (skillQuery) {
      setValue((current) => current.slice(0, skillQuery.start) + current.slice(skillQuery.end))
      setSkillQuery(null)
      setSkillSearch('')
    }
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
            readyAttachments,
            menuMention,
            selectedSkills.map((skill) => ({ ...skill })),
            workspaceReferences.map((reference) => ({ ...reference }))
          )
        : onSend(content, readyAttachments, menuMention, undefined, workspaceReferences.map((reference) => ({ ...reference }))))
    } catch (_error) {
      sent = false
    } finally {
      setSending(false)
    }
    if (sent === false) return
    setValue('')
    setMenuMention(undefined)
    setSelectedSkills([])
    setMenuQuery(null)
    setSkillOpen(false)
    items.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl))
    setItems([])
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (skillOpen && skillPickerRef.current?.handleKey(event)) return
    if (menuQuery && mentionPickerRef.current?.handleKey(event)) return
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submit()
    }
  }

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!enabled) return
    const files = Array.from(event.clipboardData.files || [])
    Array.from(event.clipboardData.items || []).forEach((item) => {
      if (item.kind !== 'file') return
      const file = item.getAsFile()
      if (file && !files.includes(file)) files.push(file)
    })
    if (!files.length) return
    event.preventDefault()
    addFiles(files)
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
      {dragging && textareaRef.current?.closest('main') ? createPortal(
        <div className="pointer-events-none absolute inset-0 z-50 grid place-items-center border-2 border-dashed border-primary/30 bg-background-panel/95 text-secondary backdrop-blur-[1px]" aria-label="拖放附件">
          <UploadCloud className="size-6" />
        </div>,
        textareaRef.current.closest('main') as Element
      ) : null}
      {items.length ? (
        <div className="mb-3" aria-label={labels.attachments}>
            <div className="mb-2 flex h-5 items-center justify-between gap-3 text-xs text-muted">
            <span>{uploadedLabel(labels.uploadedAttachments, items.length)}</span>
            <button
              type="button"
              className="inline-flex h-6 items-center gap-1 rounded border-0 bg-transparent px-1 text-xs text-secondary hover:bg-background-secondary hover:text-primary"
              aria-label={labels.clearAttachments}
              onClick={() => items.forEach(removeItem)}
            >
              <X className="size-3" />{labels.clearAttachments}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <div key={item.localId} className="relative flex h-14 w-52 min-w-0 items-center gap-2 rounded-md border border-border bg-background-panel p-2 pr-7 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
              {item.previewUrl ? (
                <img className="size-9 shrink-0 rounded object-cover" src={item.previewUrl} alt="" />
              ) : (
                <span className={cn(
                  'grid size-9 shrink-0 place-items-center rounded-md border border-border bg-background-secondary text-[9px] font-semibold text-primary',
                  (item.file.type.includes('spreadsheet') || item.file.type === 'text/csv') && 'text-positive'
                )}>{fileBadge(item.file)}</span>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium text-primary" title={item.file.name}>{item.file.name}</div>
                <div className={cn('mt-0.5 truncate text-[10px] text-muted', item.error && 'text-destructive')}>
                  {item.error || (item.status === 'uploading' ? `上传中 ${item.progress}%` : `${fileKind(item.file)} · ${formatSize(item.file.size)}`)}
                </div>
                {item.status === 'uploading' ? (
                  <div className="mt-1 h-1 overflow-hidden rounded bg-border">
                    <div className="h-full bg-primary" style={{ width: `${item.progress}%` }} />
                  </div>
                ) : null}
              </div>
              <button type="button" className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full border border-solid border-background-panel bg-muted p-0 text-background-panel shadow-sm hover:bg-primary" aria-label={`${labels.removeAttachment} ${item.file.name}`} onClick={() => removeItem(item)}>
                <X className="size-3" />
              </button>
            </div>
          ))}
          </div>
        </div>
      ) : null}
      <div>
        {workspaceReferences.length ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label="已选工作区引用">
          {workspaceReferences.map((reference) => <span key={reference.id} className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border bg-background-panel px-2 py-1 text-xs text-primary" title={reference.path}>
            {reference.isDirectory ? <Folder className="size-3.5 shrink-0" /> : <FileText className="size-3.5 shrink-0" />}<span className="truncate">{reference.name}</span>
            <button type="button" className="grid size-5 shrink-0 place-items-center border-0 bg-transparent p-0 text-muted hover:bg-accent hover:text-primary" aria-label={`移除工作区引用 ${reference.name}`} onClick={() => onRemoveWorkspaceReference?.(reference.id)}><X className="size-3" /></button>
          </span>)}
        </div> : null}
        {selectedSkills.length ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label="已选技能">
          {selectedSkills.map((skill) => <span key={skill.id} className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border bg-background-panel px-2 py-1 text-xs text-primary" title={skill.valid ? skill.description : '技能已不可用，请移除后重试'}>
            <Sparkles className="size-3.5 shrink-0" />
            <span className="truncate">{skill.name}</span>{!skill.valid ? <span className="shrink-0 text-destructive">（不可用）</span> : null}
            <button type="button" className="grid size-5 shrink-0 place-items-center border-0 bg-transparent p-0 text-muted hover:bg-accent" aria-label={`移除技能 ${skill.name}`} onClick={() => setSelectedSkills((current) => current.filter((item) => item.id !== skill.id))}><X className="size-3" /></button>
          </span>)}
        </div> : null}
        {menuMention ? <div className="mb-2 flex items-center">
          <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-primary/20 bg-accent px-2 py-1 text-xs text-primary" title={menuMention.fullPath}>
            <AtSign className="size-3.5 shrink-0" />
            <span className="truncate">{menuMention.fullPath}</span>
            <button type="button" className="grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-background hover:text-primary" aria-label="移除菜单" title="移除菜单" onClick={() => setMenuMention(undefined)}>
              <X className="size-3" />
            </button>
          </span>
        </div> : null}
        <div className="relative">
          <textarea ref={textareaRef} rows={1} disabled={disabled || sending} className="block min-h-11 w-full resize-none rounded-lg border-0 bg-background-secondary px-3 py-3 text-sm leading-5 text-primary outline outline-1 outline-transparent transition-[border-color,background-color,outline-color,box-shadow] placeholder:text-muted/90 focus:bg-background focus:outline-primary/15 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.06)] disabled:cursor-not-allowed disabled:opacity-45" placeholder={labels.inputPlaceholder} value={value} onChange={(event) => {
            const nextValue = event.target.value
            const cursor = event.target.selectionStart ?? nextValue.length
            const nextSkillQuery = skillQueryAtCursor(nextValue, cursor)
            const nextMention = menuQueryAtCursor(nextValue, cursor)
            setValue(nextValue)
            if (mentionSkillQuery) {
              if (nextMention?.query) {
                setSkillQuery(nextMention)
                setSkillSearch(nextMention.query)
                setMenuQuery(null)
              } else {
                setSkillQuery(null)
                setSkillSearch('')
                setSkillOpen(false)
                setMenuQuery(nextMention)
              }
            } else if (nextSkillQuery && agentSkills.length) {
              setSkillQuery(nextSkillQuery)
              setSkillSearch(nextSkillQuery.query)
              setSkillOpen(true)
              setMenuQuery(null)
            } else {
              setSkillQuery(null)
              setMenuQuery(nextMention)
              if (nextMention) setSkillOpen(false)
            }
          }} onClick={(event) => {
            const cursor = event.currentTarget.selectionStart ?? value.length
            const nextSkill = skillQueryAtCursor(value, cursor)
            if (nextSkill && agentSkills.length) {
              setSkillQuery(nextSkill)
              setSkillSearch(nextSkill.query)
              setSkillOpen(true)
              setMenuQuery(null)
            } else {
              const nextMention = menuQueryAtCursor(value, cursor)
              setMenuQuery(nextMention)
              if (nextMention) {
                setSkillOpen(false)
                setSkillQuery(null)
                setSkillSearch('')
              }
            }
          }} onKeyDown={onKeyDown} onPasteCapture={onPaste} aria-autocomplete="list" aria-expanded={Boolean(menuQuery || skillOpen)} aria-controls={skillOpen ? 'agui-skill-options' : menuQuery ? 'agui-mention-options' : undefined} />
          {menuQuery ? <MentionPicker ref={mentionPickerRef} open query={menuQuery} menuOptions={menuOptions} onSelectMenu={selectMenu} onOpenSkills={(typedQuery) => { const currentQuery = typedQuery || menuQuery; if (typedQuery) { setSkillQuery(currentQuery); setSkillSearch(currentQuery.query); setSkillOpen(true); setMenuQuery(null); return } const cursor = currentQuery.start; setValue((current) => current.slice(0, currentQuery.start) + current.slice(currentQuery.end)); setMenuQuery(null); setSkillQuery(null); setSkillSearch(''); setSkillOpen(true); window.setTimeout(() => textareaRef.current?.setSelectionRange(cursor, cursor), 0) }} onFocusInput={() => textareaRef.current?.focus({ preventScroll: true })} onClose={() => setMenuQuery(null)} /> : null}
          <SkillPicker ref={skillPickerRef} open={skillOpen} query={skillSearch} skills={agentSkills} selected={selectedSkills} inlineQuery={Boolean(mentionSkillQuery)} onQueryChange={setSkillSearch} onToggle={toggleSkill} onClose={() => { setSkillOpen(false); setSkillQuery(null) }} />
        </div>
        <div className="mt-2 flex min-h-8 items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            {enabled ? <>
            <input ref={inputRef} className="hidden" type="file" disabled={disabled} multiple accept={ACCEPTED_FILE_SELECTOR} onChange={(event) => {
              addFiles(Array.from(event.target.files || []))
              event.target.value = ''
            }} />
            <Button type="button" variant="ghost" size="icon" disabled={disabled} className="size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:border-primary/20 hover:bg-accent" aria-label={labels.addAttachments} title={labels.addAttachments} onClick={() => inputRef.current?.click()}>
              {icons.upload}
            </Button>
            </> : null}
            {agentSkills.length ? <Button type="button" variant="ghost" size="icon" disabled={disabled || sending} className={cn('size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:bg-accent', skillOpen && 'bg-accent text-primary')} aria-label="选择技能" title="选择技能" aria-pressed={skillOpen} onClick={() => { setSkillOpen((current) => !current); setSkillQuery(null); setSkillSearch(''); setMenuQuery(null) }}>
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
      </div>
    </form>
  )
}
