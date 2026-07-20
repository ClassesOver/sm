import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import type { WorkspaceEntry } from '../types'
import { canPreviewFile, getFilePreviewType } from './filePreviewType'
import { workspaceEntryContains, workspaceErrorMessage } from './workspaceEntryModel'

export interface WorkspacePreviewState {
  entry: WorkspaceEntry
  status: 'loading' | 'ready' | 'error' | 'unsupported'
  url?: string
  type?: string
  error?: string
}

export function useWorkspacePreview(runtime: ChatRuntime) {
  const [preview, setPreview] = useState<WorkspacePreviewState | null>(null)
  const previewRef = useRef<WorkspacePreviewState | null>(null)
  const previewRequest = useRef(0)
  previewRef.current = preview

  const closePreview = useCallback(() => {
    previewRequest.current += 1
    setPreview(null)
  }, [])

  const closeRelatedPreview = useCallback((entry: WorkspaceEntry) => {
    const current = previewRef.current
    if (!current || !workspaceEntryContains(entry, current.entry.path)) return
    previewRequest.current += 1
    setPreview(null)
  }, [])

  const openPreview = useCallback(async (entry: WorkspaceEntry) => {
    const request = ++previewRequest.current
    setPreview({ entry, status: 'loading' })
    try {
      const file = await runtime.readWorkspaceFile(entry.path)
      if (request !== previewRequest.current) return
      const type = getFilePreviewType(entry.name, file.mimeType || entry.mimeType)
      if (!canPreviewFile(type)) {
        setPreview({ entry, status: 'unsupported', type })
        return
      }
      const url = URL.createObjectURL(file.blob)
      if (request !== previewRequest.current) {
        URL.revokeObjectURL(url)
        return
      }
      setPreview({ entry, status: 'ready', type, url })
    } catch (reason) {
      if (request === previewRequest.current) {
        setPreview({ entry, status: 'error', error: workspaceErrorMessage(reason, '文件读取失败，请下载后查看。') })
      }
    }
  }, [runtime])

  useEffect(() => () => {
    previewRequest.current += 1
  }, [])

  useEffect(() => {
    const url = preview?.url
    return () => { if (url) URL.revokeObjectURL(url) }
  }, [preview?.url])

  return { preview, openPreview, closePreview, closeRelatedPreview }
}
