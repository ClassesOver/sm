import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClipboardEvent, RefObject } from 'react'
import type { AttachmentOptions, AttachmentRef } from '../types'

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

export interface UploadItem {
  localId: string
  file: File
  progress: number
  status: 'uploading' | 'ready' | 'error'
  attachment?: AttachmentRef
  previewUrl?: string
  error?: string
}

interface UseComposerAttachmentsOptions {
  attachments?: boolean | AttachmentOptions
  disabled: boolean
  textareaRef: RefObject<HTMLTextAreaElement>
  onUpload: (file: File, onProgress: (progress: number) => void) => Promise<AttachmentRef>
  onRemove: (attachmentId: string) => Promise<void>
}

function formatSize(size: number): string {
  return size < MB ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / MB).toFixed(1)} MB`
}

function acceptedModality(file: File): 'image' | 'document' | undefined {
  const extension = file.name.split('.').pop()?.toLocaleLowerCase() || ''
  return ACCEPTED_TYPES[file.type] || (REPORT_EXTENSIONS.has(extension) ? 'document' : undefined)
}

function filesFrom(transfer: DataTransfer | null): File[] {
  if (!transfer) return []
  const files = Array.from(transfer.files || [])
  Array.from(transfer.items || []).forEach((item) => {
    if (item.kind !== 'file') return
    const file = item.getAsFile()
    if (file && !files.includes(file)) files.push(file)
  })
  return files
}

function hasFiles(transfer: DataTransfer | null): boolean {
  return Boolean(transfer && (
    transfer.files.length ||
    Array.from(transfer.types || []).some((type) => String(type).toLocaleLowerCase() === 'files') ||
    Array.from(transfer.items || []).some((item) => item.kind === 'file')
  ))
}

export function useComposerAttachments({
  attachments, disabled, textareaRef, onUpload, onRemove
}: UseComposerAttachmentsOptions) {
  const config = typeof attachments === 'object' ? attachments : {}
  const enabled = attachments !== false && config.enabled !== false
  const maxFileSize = config.maxFileSize || 10 * MB
  const maxFiles = config.maxFiles || 5
  const maxTotalSize = config.maxTotalSize || 25 * MB
  const [items, setItems] = useState<UploadItem[]>([])
  const [dragging, setDragging] = useState(false)
  const itemsRef = useRef<UploadItem[]>([])
  const dragDepth = useRef(0)
  const onUploadRef = useRef(onUpload)
  const onRemoveRef = useRef(onRemove)
  itemsRef.current = items
  onUploadRef.current = onUpload
  onRemoveRef.current = onRemove

  const updateItem = useCallback((localId: string, values: Partial<UploadItem>) => {
    setItems((current) => {
      return current.map((item) => item.localId === localId ? { ...item, ...values } : item)
    })
  }, [])

  const addFiles = useCallback((files: File[]) => {
    if (!enabled || disabled || !files.length) return
    const current = itemsRef.current
    const next: UploadItem[] = []
    let count = current.length
    let totalSize = current.reduce((sum, item) => sum + item.file.size, 0)
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
    const updated = [...current, ...next]
    itemsRef.current = updated
    setItems(updated)
    next.filter((item) => item.status === 'uploading').forEach((item) => {
      void onUploadRef.current(item.file, (progress) => updateItem(item.localId, { progress })).then(
        (attachment) => updateItem(item.localId, { attachment, progress: 100, status: 'ready' }),
        (error) => updateItem(item.localId, { error: (error as Error)?.message || '上传失败', status: 'error' })
      )
    })
  }, [disabled, enabled, maxFileSize, maxFiles, maxTotalSize, updateItem])

  const removeItem = useCallback((item: UploadItem) => {
    const next = itemsRef.current.filter((candidate) => candidate.localId !== item.localId)
    itemsRef.current = next
    setItems(next)
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    if (item.attachment) void onRemoveRef.current(item.attachment.id)
  }, [])

  const clearItems = useCallback(() => {
    itemsRef.current.forEach(removeItem)
  }, [removeItem])

  const resetItems = useCallback(() => {
    itemsRef.current.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl))
    itemsRef.current = []
    setItems([])
  }, [])

  const handlePaste = useCallback((event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!enabled) return
    const files = filesFrom(event.clipboardData)
    if (!files.length) return
    event.preventDefault()
    addFiles(files)
  }, [addFiles, enabled])

  useEffect(() => {
    if (!enabled || disabled) return
    const dropRegion = textareaRef.current?.closest('main')
    if (!dropRegion) return
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
  }, [addFiles, disabled, enabled, textareaRef])

  useEffect(() => () => {
    itemsRef.current.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl))
  }, [])

  return {
    items,
    dragging,
    enabled,
    acceptedFileSelector: ACCEPTED_FILE_SELECTOR,
    readyAttachments: items.flatMap((item) => item.attachment ? [item.attachment] : []),
    addFiles,
    removeItem,
    clearItems,
    resetItems,
    handlePaste
  }
}
