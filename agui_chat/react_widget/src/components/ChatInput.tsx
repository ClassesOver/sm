import { AtSign, UploadCloud, X } from 'lucide-react'
import { ClipboardEvent, FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type {
  AttachmentOptions, AttachmentRef, ChatIcons, ChatLabels, MenuMention, MenuMentionOption
} from '../types'
import { cn } from '../lib'
import { Button } from './Button'

const ACCEPTED_TYPES: Record<string, 'image' | 'document'> = {
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/webp': 'image',
  'application/pdf': 'document',
  'text/plain': 'document',
  'text/csv': 'document',
  'application/json': 'document',
  'application/vnd.ms-excel': 'document',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'document'
}
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
  onSend: (content: string, attachments: AttachmentRef[], menuMention?: MenuMention) => void
  onStop: () => void
  onUpload: (file: File, onProgress: (progress: number) => void) => Promise<AttachmentRef>
  onRemove: (attachmentId: string) => Promise<void>
  labels: ChatLabels
  icons: ChatIcons
}

export interface MenuQuery {
  start: number
  end: number
  query: string
}

export function menuQueryAtCursor(value: string, cursor: number): MenuQuery | null {
  const prefix = value.slice(0, cursor)
  const match = prefix.match(/(^|\s)@([^\s@]*)$/)
  if (!match || match.index === undefined) return null
  const start = match.index + match[1].length
  return { start, end: cursor, query: match[2] }
}

function formatSize(size: number): string {
  return size < MB ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / MB).toFixed(1)} MB`
}

function fileBadge(file: File): string {
  const extension = file.name.split('.').pop()?.toUpperCase()
  return extension && extension.length <= 4 ? extension : 'FILE'
}

function uploadedLabel(template: string, count: number): string {
  return template.replace('{count}', String(count))
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
  running, disabled = false, attachments, menuOptions, onSend, onStop, onUpload, onRemove,
  labels, icons
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const [menuMention, setMenuMention] = useState<MenuMention | undefined>()
  const [menuQuery, setMenuQuery] = useState<MenuQuery | null>(null)
  const [activeMenuIndex, setActiveMenuIndex] = useState(0)
  const [items, setItems] = useState<UploadItem[]>([])
  const [dragging, setDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragDepth = useRef(0)
  const config = typeof attachments === 'object' ? attachments : {}
  const enabled = attachments !== false && config.enabled !== false
  const maxFileSize = config.maxFileSize || 10 * MB
  const maxFiles = config.maxFiles || 5
  const maxTotalSize = config.maxTotalSize || 25 * MB
  const normalizedMenuQuery = menuQuery?.query.trim().toLocaleLowerCase() || ''
  const filteredMenus = menuQuery
    ? menuOptions.filter((option) =>
        !normalizedMenuQuery || option.fullPath.toLocaleLowerCase().includes(normalizedMenuQuery)
      ).slice(0, 8)
    : []

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
      if (!ACCEPTED_TYPES[file.type]) error = '不支持的文件类型'
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
        previewUrl: ACCEPTED_TYPES[file.type] === 'image' ? URL.createObjectURL(file) : undefined
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
    const hasFiles = (event: globalThis.DragEvent) =>
      Array.from(event.dataTransfer?.types || []).includes('Files')
    const insideDropRegion = (event: globalThis.DragEvent) => dropRegion.contains(event.target as Node)
    const dragEnter = (event: globalThis.DragEvent) => {
      if (!hasFiles(event) || !insideDropRegion(event)) return
      event.preventDefault()
      dragDepth.current += 1
      setDragging(true)
    }
    const dragOver = (event: globalThis.DragEvent) => {
      if (hasFiles(event) && insideDropRegion(event)) event.preventDefault()
    }
    const dragLeave = (event: globalThis.DragEvent) => {
      if (!dragging && dragDepth.current === 0) return
      event.preventDefault()
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setDragging(false)
    }
    const drop = (event: globalThis.DragEvent) => {
      const files = Array.from(event.dataTransfer?.files || [])
      dragDepth.current = 0
      setDragging(false)
      if (!files.length || !insideDropRegion(event)) return
      event.preventDefault()
      addFiles(files)
    }
    window.addEventListener('dragenter', dragEnter)
    window.addEventListener('dragover', dragOver)
    window.addEventListener('dragleave', dragLeave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', dragEnter)
      window.removeEventListener('dragover', dragOver)
      window.removeEventListener('dragleave', dragLeave)
      window.removeEventListener('drop', drop)
    }
  }, [disabled, enabled, dragging, items])

  const removeItem = (item: UploadItem) => {
    setItems((current) => current.filter((candidate) => candidate.localId !== item.localId))
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    if (item.attachment) void onRemove(item.attachment.id)
  }

  const readyAttachments = items.flatMap((item) => item.attachment ? [item.attachment] : [])
  const canSend = !running && !disabled && !items.some((item) => item.status !== 'ready') &&
    (!!value.trim() || readyAttachments.length > 0 || !!menuMention)

  const selectMenu = (option: MenuMentionOption) => {
    if (!menuQuery) return
    const cursor = menuQuery.start
    setValue((current) => current.slice(0, menuQuery.start) + current.slice(menuQuery.end))
    setMenuMention({ ...option, path: [...option.path], valid: true })
    setMenuQuery(null)
    setActiveMenuIndex(0)
    window.setTimeout(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(cursor, cursor)
    }, 0)
  }

  const submit = () => {
    if (!canSend) return
    const content = value.trim()
    setValue('')
    const selectedMenu = menuMention
    setMenuMention(undefined)
    setMenuQuery(null)
    items.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl))
    setItems([])
    onSend(content, readyAttachments, selectedMenu)
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuQuery) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setMenuQuery(null)
        return
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        const direction = event.key === 'ArrowDown' ? 1 : -1
        setActiveMenuIndex((current) => filteredMenus.length
          ? (current + direction + filteredMenus.length) % filteredMenus.length
          : 0)
        return
      }
      if (event.key === 'Enter') {
        event.preventDefault()
        if (filteredMenus[activeMenuIndex]) selectMenu(filteredMenus[activeMenuIndex])
        return
      }
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!enabled) return
    const files = Array.from(event.clipboardData.files || [])
    if (!files.length) return
    event.preventDefault()
    addFiles(files)
  }

  return (
    <form
      className="relative w-full shrink-0 border border-solid border-border/60 bg-background-panel px-4 pb-3 pt-3 shadow-none sm:px-6"
      onClick={(event) => {
        const target = event.target as HTMLElement
        if (!target.closest('button, a, input, textarea')) textareaRef.current?.focus()
      }}
      onSubmit={(event: FormEvent) => { event.preventDefault(); submit() }}
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
          <textarea ref={textareaRef} rows={1} disabled={disabled} className="block min-h-11 w-full resize-none rounded-lg border-0 bg-background-secondary px-3 py-3 text-sm leading-5 text-primary outline-none placeholder:text-muted/90 focus:bg-background focus:ring-1 focus:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-45" placeholder={labels.inputPlaceholder} value={value} onChange={(event) => {
            const nextValue = event.target.value
            const cursor = event.target.selectionStart ?? nextValue.length
            setValue(nextValue)
            setActiveMenuIndex(0)
            setMenuQuery(menuQueryAtCursor(nextValue, cursor))
          }} onClick={(event) => {
            const cursor = event.currentTarget.selectionStart ?? value.length
            setMenuQuery(menuQueryAtCursor(value, cursor))
          }} onBlur={() => window.setTimeout(() => setMenuQuery(null), 120)} onKeyDown={onKeyDown} onPaste={onPaste} aria-autocomplete="list" aria-expanded={Boolean(menuQuery)} />
          {menuQuery ? <div role="listbox" className="absolute bottom-full left-0 right-0 z-40 mb-1 max-h-64 overflow-y-auto rounded-md border border-border bg-background-panel p-1 shadow-lg">
            {filteredMenus.length ? filteredMenus.map((option, index) => <button key={option.menuId} type="button" role="option" aria-selected={index === activeMenuIndex} className={cn('flex w-full items-center gap-2 rounded border-0 bg-transparent px-2.5 py-2 text-left text-xs text-secondary hover:bg-accent', index === activeMenuIndex && 'bg-accent text-primary')} onMouseDown={(event) => event.preventDefault()} onClick={() => selectMenu(option)}>
              <AtSign className="size-3.5 shrink-0 text-muted" />
              <span className="min-w-0 flex-1 truncate" title={option.fullPath}>{option.fullPath}</span>
            </button>) : <div className="px-2.5 py-2 text-xs text-muted">没有匹配的菜单</div>}
          </div> : null}
        </div>
        <div className="mt-2 flex min-h-8 items-center justify-between gap-2">
          {enabled ? (
            <>
            <input ref={inputRef} className="hidden" type="file" disabled={disabled} multiple accept={Object.keys(ACCEPTED_TYPES).join(',')} onChange={(event) => {
              addFiles(Array.from(event.target.files || []))
              event.target.value = ''
            }} />
            <Button type="button" variant="ghost" size="icon" disabled={disabled} className="size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:border-primary/20 hover:bg-accent" aria-label={labels.addAttachments} title={labels.addAttachments} onClick={() => inputRef.current?.click()}>
              {icons.upload}
            </Button>
            </>
          ) : <span />}
          <Button type={running ? 'button' : 'submit'} variant="primary" size="icon" className={cn('size-8 shrink-0 rounded-md shadow-none disabled:border-border disabled:bg-border disabled:text-muted', running && 'ring-1 ring-primary/15')} disabled={running ? false : disabled || !canSend} aria-label={running ? labels.stopGenerating : labels.sendMessage} title={running ? labels.stopGenerating : labels.sendMessage} onClick={running ? onStop : undefined}>
            {running ? icons.stop : icons.send}
          </Button>
        </div>
      </div>
    </form>
  )
}
