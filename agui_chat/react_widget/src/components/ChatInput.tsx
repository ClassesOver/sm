import { AtSign, Database, Filter, Menu, SlidersHorizontal, UploadCloud, X } from 'lucide-react'
import { ClipboardEvent, FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type {
  AttachmentOptions, AttachmentRef, ChatIcons, ChatLabels, HostBridge, MenuMention,
  MenuMentionOption, MentionAction, MentionCandidate, MentionReference, MentionScope
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
const MAX_MENTIONS = 5
const PAGE_ACTIONS = new Set<MentionAction>(['open', 'create', 'view', 'edit', 'apply'])
const ACTION_LABELS: Record<MentionAction, string> = {
  read: '引用数据', open: '打开', create: '新建', view: '打开查看', edit: '打开编辑', apply: '应用'
}
const SCOPE_LABELS: Array<[MentionScope, string]> = [
  ['all', '全部'], ['menu', '菜单'], ['record', '记录'],
  ['saved_filter', '收藏'], ['current_filter', '当前筛选']
]

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
  hostBridge?: HostBridge
  onSend: (
    content: string, attachments: AttachmentRef[], mentions?: MentionReference[] | MenuMention
  ) => void
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

function MentionIcon({ kind }: { kind: MentionCandidate['kind'] | MentionReference['kind'] }) {
  if (kind === 'menu') return <Menu className="size-3.5 shrink-0" />
  if (kind === 'record') return <Database className="size-3.5 shrink-0" />
  if (kind === 'saved_filter') return <Filter className="size-3.5 shrink-0" />
  return <SlidersHorizontal className="size-3.5 shrink-0" />
}

export function ChatInput({
  running, disabled = false, attachments, menuOptions, hostBridge, onSend, onStop, onUpload, onRemove,
  labels, icons
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const [menuMention, setMenuMention] = useState<MenuMention | undefined>()
  const [mentions, setMentions] = useState<MentionReference[]>([])
  const [menuQuery, setMenuQuery] = useState<MenuQuery | null>(null)
  const [activeMenuIndex, setActiveMenuIndex] = useState(0)
  const [scope, setScope] = useState<MentionScope>('all')
  const [modelScope, setModelScope] = useState('')
  const [candidates, setCandidates] = useState<MentionCandidate[]>([])
  const [modelScopes, setModelScopes] = useState<Array<{ model: string; label: string }>>([])
  const [pendingCandidate, setPendingCandidate] = useState<MentionCandidate | null>(null)
  const [mentionLoading, setMentionLoading] = useState(false)
  const [mentionBinding, setMentionBinding] = useState(false)
  const [mentionError, setMentionError] = useState('')
  const [items, setItems] = useState<UploadItem[]>([])
  const [dragging, setDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragDepth = useRef(0)
  const mentionRequest = useRef(0)
  const unifiedMentions = Boolean(hostBridge?.searchMentions && hostBridge?.bindMention)
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

  useEffect(() => {
    if (!unifiedMentions || !menuQuery || !hostBridge?.searchMentions) return
    const query = menuQuery.query.trim()
    const requestId = ++mentionRequest.current
    setPendingCandidate(null)
    setMentionError('')
    if (scope !== 'menu' && query.length < 2) {
      setCandidates([])
      setMentionLoading(false)
      return
    }
    setMentionLoading(true)
    const timer = window.setTimeout(() => {
      void hostBridge.searchMentions?.({
        query, scope, modelScope: modelScope || undefined
      }).then((result) => {
        if (requestId !== mentionRequest.current) return
        if (result?.ok === false) {
          setCandidates([])
          setMentionError(result.error || result.code || '对象搜索失败')
        } else {
          setCandidates(result?.candidates || [])
          setModelScopes(result?.modelScopes || [])
        }
      }, (error) => {
        if (requestId !== mentionRequest.current) return
        setCandidates([])
        setMentionError((error as Error)?.message || '对象搜索失败')
      }).finally(() => {
        if (requestId === mentionRequest.current) setMentionLoading(false)
      })
    }, 300)
    return () => window.clearTimeout(timer)
  }, [hostBridge, menuQuery?.query, modelScope, scope, unifiedMentions])

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
    (!!value.trim() || readyAttachments.length > 0 || !!menuMention || mentions.length > 0)

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

  const bindCandidate = async (candidate: MentionCandidate, action: MentionAction) => {
    if (!menuQuery || !hostBridge?.bindMention || mentionBinding) return
    setMentionError('')
    if (mentions.length >= MAX_MENTIONS) {
      setMentionError('每条消息最多引用 5 个对象')
      return
    }
    if (mentions.some((mention) => mention.resourceKey === candidate.resourceKey)) {
      setMentionError('不能重复引用同一对象')
      return
    }
    if (PAGE_ACTIONS.has(action) && mentions.some((mention) => mention.pageAction)) {
      setMentionError('每条消息最多包含 1 个页面动作')
      return
    }
    setMentionBinding(true)
    try {
      const result = await hostBridge.bindMention({
        candidateToken: candidate.candidateToken, action
      })
      if (!result?.ok || !result.reference) {
        setMentionError(result?.error || result?.code || '对象绑定失败')
        return
      }
      const cursor = menuQuery.start
      setValue((current) => current.slice(0, menuQuery.start) + current.slice(menuQuery.end))
      setMentions((current) => [...current, result.reference as MentionReference])
      setMenuQuery(null)
      setPendingCandidate(null)
      setCandidates([])
      setActiveMenuIndex(0)
      window.setTimeout(() => {
        textareaRef.current?.focus()
        textareaRef.current?.setSelectionRange(cursor, cursor)
      }, 0)
    } catch (error) {
      setMentionError((error as Error)?.message || '对象绑定失败')
    } finally {
      setMentionBinding(false)
    }
  }

  const submit = () => {
    if (!canSend) return
    const content = value.trim()
    setValue('')
    const selectedMentions = unifiedMentions ? mentions : menuMention
    setMenuMention(undefined)
    setMentions([])
    setMenuQuery(null)
    items.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl))
    setItems([])
    onSend(content, readyAttachments, selectedMentions || undefined)
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuQuery) {
      if (event.key === 'Escape') {
        event.preventDefault()
        if (pendingCandidate) {
          setPendingCandidate(null)
          setActiveMenuIndex(0)
          return
        }
        setMenuQuery(null)
        return
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        const direction = event.key === 'ArrowDown' ? 1 : -1
        const length = unifiedMentions
          ? pendingCandidate?.actions.length || candidates.length
          : filteredMenus.length
        setActiveMenuIndex((current) => length
          ? (current + direction + length) % length
          : 0)
        return
      }
      if (event.key === 'Enter') {
        event.preventDefault()
        if (unifiedMentions) {
          if (pendingCandidate?.actions[activeMenuIndex]) {
            void bindCandidate(pendingCandidate, pendingCandidate.actions[activeMenuIndex])
          } else if (candidates[activeMenuIndex]) {
            setPendingCandidate(candidates[activeMenuIndex])
            setActiveMenuIndex(0)
          }
        } else if (filteredMenus[activeMenuIndex]) {
          selectMenu(filteredMenus[activeMenuIndex])
        }
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
        {mentions.length ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label="已选对象引用">
          {mentions.map((mention) => <span key={mention.id} className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-primary/20 bg-accent px-2 py-1 text-xs text-primary" title={`${mention.detail} · ${ACTION_LABELS[mention.action]}`}>
            <MentionIcon kind={mention.kind} />
            <span className="truncate">{mention.label}</span>
            <span className="shrink-0 text-muted">{ACTION_LABELS[mention.action]}</span>
            <button type="button" className="grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-background hover:text-primary" aria-label={`移除引用 ${mention.label}`} title="移除引用" onClick={() => setMentions((current) => current.filter((item) => item.id !== mention.id))}>
              <X className="size-3" />
            </button>
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
          {menuQuery ? <div role="listbox" className="absolute bottom-full left-0 right-0 z-40 mb-1 max-h-72 overflow-y-auto rounded-md border border-border bg-background-panel p-1 shadow-lg">
            {unifiedMentions ? <>
              <div className="sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b border-border bg-background-panel p-1.5">
                {SCOPE_LABELS.map(([value, label]) => <button key={value} type="button" className={cn('h-7 rounded px-2 text-[11px] text-muted hover:bg-accent hover:text-primary', scope === value && 'bg-accent text-primary')} aria-pressed={scope === value} onMouseDown={(event) => event.preventDefault()} onClick={() => { setScope(value); setActiveMenuIndex(0); setPendingCandidate(null) }}>{label}</button>)}
                {modelScopes.length ? <select className="ml-auto h-7 min-w-0 max-w-40 rounded border border-border bg-background-panel px-1.5 text-[11px] text-secondary" aria-label="搜索模型" value={modelScope} onMouseDown={(event) => event.preventDefault()} onChange={(event) => { setModelScope(event.target.value); setActiveMenuIndex(0) }}>
                  <option value="">优先模型</option>
                  {modelScopes.map((item) => <option key={item.model} value={item.model}>{item.label}</option>)}
                </select> : null}
              </div>
              {pendingCandidate ? <div className="p-1">
                <div className="flex min-w-0 items-center gap-2 px-2.5 py-2 text-xs text-primary">
                  <MentionIcon kind={pendingCandidate.kind} />
                  <span className="min-w-0 flex-1 truncate" title={pendingCandidate.detail}>{pendingCandidate.label}</span>
                </div>
                <div className="flex flex-wrap gap-1 px-2 pb-2">
                  {pendingCandidate.actions.map((action, index) => <button key={action} type="button" role="option" aria-selected={index === activeMenuIndex} disabled={mentionBinding} className={cn('h-8 rounded border border-border bg-background-panel px-2.5 text-xs text-secondary hover:bg-accent hover:text-primary disabled:opacity-45', index === activeMenuIndex && 'bg-accent text-primary')} onMouseDown={(event) => event.preventDefault()} onClick={() => void bindCandidate(pendingCandidate, action)}>{ACTION_LABELS[action]}</button>)}
                </div>
              </div> : candidates.length ? candidates.map((candidate, index) => <button key={candidate.candidateToken} type="button" role="option" aria-selected={index === activeMenuIndex} className={cn('flex w-full items-center gap-2 rounded border-0 bg-transparent px-2.5 py-2 text-left text-xs text-secondary hover:bg-accent', index === activeMenuIndex && 'bg-accent text-primary')} onMouseDown={(event) => event.preventDefault()} onClick={() => { setPendingCandidate(candidate); setActiveMenuIndex(0) }}>
                <MentionIcon kind={candidate.kind} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-primary" title={candidate.label}>{candidate.label}</span>
                  <span className="block truncate text-[10px] text-muted" title={candidate.detail}>{candidate.detail}</span>
                </span>
              </button>) : <div className="px-2.5 py-2 text-xs text-muted">{mentionLoading ? '搜索中' : mentionError || '没有匹配的对象'}</div>}
              {mentionError && candidates.length ? <div className="px-2.5 py-2 text-xs text-destructive">{mentionError}</div> : null}
            </> : filteredMenus.length ? filteredMenus.map((option, index) => <button key={option.menuId} type="button" role="option" aria-selected={index === activeMenuIndex} className={cn('flex w-full items-center gap-2 rounded border-0 bg-transparent px-2.5 py-2 text-left text-xs text-secondary hover:bg-accent', index === activeMenuIndex && 'bg-accent text-primary')} onMouseDown={(event) => event.preventDefault()} onClick={() => selectMenu(option)}>
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
