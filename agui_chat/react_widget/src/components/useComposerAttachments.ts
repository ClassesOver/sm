import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClipboardEvent, RefObject } from 'react'
import type { AttachmentOptions, AttachmentRef } from '../types'
import {
  ACCEPTED_ATTACHMENT_SELECTOR,
  getAttachmentPolicy,
  validateAttachmentFiles
} from './attachmentPolicy'
import { filesFromDataTransfer, useFileDropTarget } from './useFileDropTarget'

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

export function useComposerAttachments({
  attachments, disabled, textareaRef, onUpload, onRemove
}: UseComposerAttachmentsOptions) {
  const policy = getAttachmentPolicy(attachments)
  const { enabled, maxFileSize, maxFiles, maxTotalSize } = policy
  const [items, setItems] = useState<UploadItem[]>([])
  const itemsRef = useRef<UploadItem[]>([])
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
    const next = validateAttachmentFiles(
      files,
      current.map((item) => item.file),
      { enabled, maxFileSize, maxFiles, maxTotalSize }
    ).map(({ file, modality, error }): UploadItem => ({
      localId: `${Date.now()}-${Math.random()}`,
      file,
      progress: 0,
      status: error ? 'error' : 'uploading',
      error,
      previewUrl: modality === 'image' ? URL.createObjectURL(file) : undefined
    }))
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
  const { dragging } = useFileDropTarget({
    enabled,
    disabled,
    anchorRef: textareaRef,
    onFiles: addFiles
  })

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
    const files = filesFromDataTransfer(event.clipboardData)
    if (!files.length) return
    event.preventDefault()
    addFiles(files)
  }, [addFiles, enabled])

  useEffect(() => () => {
    itemsRef.current.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl))
  }, [])

  return {
    items,
    dragging,
    enabled,
    acceptedFileSelector: ACCEPTED_ATTACHMENT_SELECTOR,
    readyAttachments: items.flatMap((item) => item.attachment ? [item.attachment] : []),
    addFiles,
    removeItem,
    clearItems,
    resetItems,
    handlePaste
  }
}
