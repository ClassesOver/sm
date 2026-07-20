import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { WorkspaceEntry, WorkspaceReference } from '../types'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import { canPreviewFile, getFilePreviewType } from './filePreviewType'
import type { WorkspaceSortDirection, WorkspaceSortKey } from './WorkspaceToolbar'

export const MAX_WORKSPACE_REFERENCES = 5

export interface WorkspacePreviewState {
  entry: WorkspaceEntry
  status: 'loading' | 'ready' | 'error' | 'unsupported'
  url?: string
  type?: string
  error?: string
}

interface UseWorkspaceDirectoryOptions {
  runtime: ChatRuntime
  threadId: string
  references: WorkspaceReference[]
  onToggleReference: (entry: WorkspaceEntry) => void
  onDeleted: (entry: WorkspaceEntry) => void
}

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

function compareEntries(left: WorkspaceEntry, right: WorkspaceEntry, key: WorkspaceSortKey, direction: WorkspaceSortDirection): number {
  if (left.isDirectory !== right.isDirectory) return left.isDirectory ? -1 : 1

  let result = 0
  if (key === 'name') {
    result = collator.compare(left.name, right.name)
  } else if (key === 'size') {
    const leftSize = Number.isFinite(left.size) ? left.size : 0
    const rightSize = Number.isFinite(right.size) ? right.size : 0
    result = leftSize - rightSize
  } else {
    const leftTime = new Date(left.modifiedAt).getTime()
    const rightTime = new Date(right.modifiedAt).getTime()
    const leftValid = Number.isFinite(leftTime)
    const rightValid = Number.isFinite(rightTime)
    if (leftValid !== rightValid) return leftValid ? -1 : 1
    if (leftValid && rightValid) result = leftTime - rightTime
  }

  if (result === 0) result = collator.compare(left.name, right.name)
  return direction === 'asc' ? result : -result
}

function sortEntries(entries: WorkspaceEntry[], key: WorkspaceSortKey, direction: WorkspaceSortDirection): WorkspaceEntry[] {
  return [...entries].sort((left, right) => compareEntries(left, right, key, direction))
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback
}

function isInside(entry: WorkspaceEntry, path: string): boolean {
  return entry.path === path || (entry.isDirectory && path.startsWith(`${entry.path}/`))
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
    if (!current || !isInside(entry, current.entry.path)) return
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
        setPreview({ entry, status: 'error', error: errorMessage(reason, '文件读取失败，请下载后查看。') })
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

export function useWorkspaceDirectory({
  runtime, threadId, references, onToggleReference, onDeleted
}: UseWorkspaceDirectoryOptions) {
  const [path, setPath] = useState('')
  const [entries, setEntries] = useState<WorkspaceEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<WorkspaceSortKey>('name')
  const [sortDirection, setSortDirection] = useState<WorkspaceSortDirection>('asc')
  const [confirmDelete, setConfirmDelete] = useState<WorkspaceEntry | null>(null)
  const [deletingPath, setDeletingPath] = useState('')
  const listRequest = useRef(0)

  const load = useCallback(async (preserve = false) => {
    const request = ++listRequest.current
    setLoading(true)
    setListError('')
    if (!preserve) setEntries([])
    try {
      const nextEntries = await runtime.listWorkspace(path)
      if (request === listRequest.current) setEntries(nextEntries)
    } catch (reason) {
      if (request === listRequest.current) setListError(errorMessage(reason, '工作区加载失败，请重试。'))
    } finally {
      if (request === listRequest.current) setLoading(false)
    }
  }, [path, runtime])

  useEffect(() => { void load() }, [load, threadId])
  useEffect(() => () => { listRequest.current += 1 }, [])

  const navigate = useCallback((nextPath: string) => {
    setPath(nextPath)
    setSearch('')
    setConfirmDelete(null)
    setActionError('')
    setNotice('')
  }, [])

  const visibleEntries = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('zh-CN')
    const filtered = query
      ? entries.filter((entry) => entry.name.toLocaleLowerCase('zh-CN').includes(query))
      : entries
    return sortEntries(filtered, sortKey, sortDirection)
  }, [entries, search, sortDirection, sortKey])

  const clearMessages = useCallback(() => {
    setActionError('')
    setNotice('')
  }, [])

  const download = useCallback((entry: WorkspaceEntry) => {
    setActionError('')
    void runtime.downloadWorkspaceFile(entry.path).catch((reason) => {
      setActionError(errorMessage(reason, '文件下载失败，请重试。'))
    })
  }, [runtime])

  const requestDelete = useCallback((entry: WorkspaceEntry) => {
    setConfirmDelete(entry)
    setActionError('')
  }, [])

  const cancelDelete = useCallback(() => {
    setConfirmDelete(null)
  }, [])

  const remove = useCallback(async () => {
    const entry = confirmDelete
    if (!entry || deletingPath) return
    setDeletingPath(entry.path)
    setActionError('')
    try {
      await runtime.deleteWorkspaceEntry(entry.path, entry.isDirectory)
      setEntries((current) => current.filter((candidate) => candidate.path !== entry.path))
      onDeleted(entry)
      setConfirmDelete(null)
      void load(true)
    } catch (reason) {
      setActionError(errorMessage(reason, '删除失败，请重试。'))
    } finally {
      setDeletingPath('')
    }
  }, [confirmDelete, deletingPath, load, onDeleted, runtime])

  const toggleReference = useCallback((entry: WorkspaceEntry) => {
    const selected = references.some((item) => item.path === entry.path)
    if (!selected && references.length >= MAX_WORKSPACE_REFERENCES) {
      setNotice(`工作区引用最多 ${MAX_WORKSPACE_REFERENCES} 个，请先移除一个已选引用。`)
      return
    }
    setNotice('')
    onToggleReference(entry)
  }, [onToggleReference, references])

  const toggleSortDirection = useCallback(() => {
    setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
  }, [])

  return {
    path,
    entries,
    visibleEntries,
    loading,
    listError,
    actionError,
    notice,
    search,
    sortKey,
    sortDirection,
    confirmDelete,
    deletingPath,
    referenceLimit: MAX_WORKSPACE_REFERENCES,
    setSearch,
    setSortKey,
    load,
    navigate,
    clearMessages,
    download,
    requestDelete,
    remove,
    cancelDelete,
    toggleReference,
    toggleSortDirection
  }
}
