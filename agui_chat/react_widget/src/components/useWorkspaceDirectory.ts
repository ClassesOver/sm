import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import type { WorkspaceEntry, WorkspaceReference } from '../types'
import { MAX_WORKSPACE_REFERENCES } from './useWorkspaceReferences'
import {
  getVisibleWorkspaceEntries,
  workspaceErrorMessage,
  type WorkspaceSortDirection,
  type WorkspaceSortKey
} from './workspaceEntryModel'

interface UseWorkspaceDirectoryOptions {
  runtime: ChatRuntime
  threadId: string
  references: WorkspaceReference[]
  onToggleReference: (entry: WorkspaceEntry) => void
  onDeleted: (entry: WorkspaceEntry) => void
}

export interface WorkspaceDirectoryState {
  entries: WorkspaceEntry[]
  loading: boolean
  listError: string
  actionError: string
  notice: string
  confirmDelete: WorkspaceEntry | null
  deletingPath: string
}

export type WorkspaceDirectoryAction =
  | { type: 'load_started'; preserve: boolean }
  | { type: 'load_succeeded'; entries: WorkspaceEntry[] }
  | { type: 'load_failed'; error: string }
  | { type: 'navigated' }
  | { type: 'messages_cleared' }
  | { type: 'action_error_cleared' }
  | { type: 'action_failed'; error: string }
  | { type: 'notice_changed'; notice: string }
  | { type: 'delete_requested'; entry: WorkspaceEntry }
  | { type: 'delete_cancelled' }
  | { type: 'delete_started'; path: string }
  | { type: 'delete_succeeded'; path: string }
  | { type: 'delete_failed'; error: string }

export const INITIAL_WORKSPACE_DIRECTORY_STATE: WorkspaceDirectoryState = {
  entries: [],
  loading: false,
  listError: '',
  actionError: '',
  notice: '',
  confirmDelete: null,
  deletingPath: ''
}

export function workspaceDirectoryReducer(
  state: WorkspaceDirectoryState,
  action: WorkspaceDirectoryAction
): WorkspaceDirectoryState {
  switch (action.type) {
    case 'load_started':
      return {
        ...state,
        entries: action.preserve ? state.entries : [],
        loading: true,
        listError: ''
      }
    case 'load_succeeded':
      return { ...state, entries: action.entries, loading: false }
    case 'load_failed':
      return { ...state, loading: false, listError: action.error }
    case 'navigated':
      return { ...state, actionError: '', notice: '', confirmDelete: null }
    case 'messages_cleared':
      return { ...state, actionError: '', notice: '' }
    case 'action_error_cleared':
      return { ...state, actionError: '' }
    case 'action_failed':
      return { ...state, actionError: action.error }
    case 'notice_changed':
      return { ...state, notice: action.notice }
    case 'delete_requested':
      return { ...state, confirmDelete: action.entry, actionError: '' }
    case 'delete_cancelled':
      return { ...state, confirmDelete: null }
    case 'delete_started':
      return { ...state, deletingPath: action.path, actionError: '' }
    case 'delete_succeeded':
      return {
        ...state,
        entries: state.entries.filter((entry) => entry.path !== action.path),
        confirmDelete: null,
        deletingPath: ''
      }
    case 'delete_failed':
      return { ...state, deletingPath: '', actionError: action.error }
  }
}

export function useWorkspaceDirectory({
  runtime, threadId, references, onToggleReference, onDeleted
}: UseWorkspaceDirectoryOptions) {
  const [path, setPath] = useState('')
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<WorkspaceSortKey>('name')
  const [sortDirection, setSortDirection] = useState<WorkspaceSortDirection>('asc')
  const [state, dispatch] = useReducer(workspaceDirectoryReducer, INITIAL_WORKSPACE_DIRECTORY_STATE)
  const listRequest = useRef(0)

  const load = useCallback(async (preserve = false) => {
    const request = ++listRequest.current
    dispatch({ type: 'load_started', preserve })
    try {
      const entries = await runtime.listWorkspace(path)
      if (request === listRequest.current) dispatch({ type: 'load_succeeded', entries })
    } catch (reason) {
      if (request === listRequest.current) {
        dispatch({ type: 'load_failed', error: workspaceErrorMessage(reason, '工作区加载失败，请重试。') })
      }
    }
  }, [path, runtime])

  useEffect(() => { void load() }, [load, threadId])
  useEffect(() => runtime.subscribeWorkspace(() => { void load(true) }), [load, runtime])
  useEffect(() => () => { listRequest.current += 1 }, [])

  const navigate = useCallback((nextPath: string) => {
    setPath(nextPath)
    setSearch('')
    dispatch({ type: 'navigated' })
  }, [])

  const visibleEntries = useMemo(() => {
    return getVisibleWorkspaceEntries(state.entries, search, sortKey, sortDirection)
  }, [search, sortDirection, sortKey, state.entries])

  const clearMessages = useCallback(() => {
    dispatch({ type: 'messages_cleared' })
  }, [])

  const download = useCallback((entry: WorkspaceEntry) => {
    dispatch({ type: 'action_error_cleared' })
    void runtime.downloadWorkspaceFile(entry.path).catch((reason) => {
      dispatch({ type: 'action_failed', error: workspaceErrorMessage(reason, '文件下载失败，请重试。') })
    })
  }, [runtime])

  const requestDelete = useCallback((entry: WorkspaceEntry) => {
    dispatch({ type: 'delete_requested', entry })
  }, [])

  const cancelDelete = useCallback(() => {
    dispatch({ type: 'delete_cancelled' })
  }, [])

  const remove = useCallback(async () => {
    const entry = state.confirmDelete
    if (!entry || state.deletingPath) return
    dispatch({ type: 'delete_started', path: entry.path })
    try {
      await runtime.deleteWorkspaceEntry(entry.path, entry.isDirectory)
      onDeleted(entry)
      dispatch({ type: 'delete_succeeded', path: entry.path })
      void load(true)
    } catch (reason) {
      dispatch({ type: 'delete_failed', error: workspaceErrorMessage(reason, '删除失败，请重试。') })
    }
  }, [load, onDeleted, runtime, state.confirmDelete, state.deletingPath])

  const toggleReference = useCallback((entry: WorkspaceEntry) => {
    const selected = references.some((item) => item.path === entry.path)
    if (!selected && references.length >= MAX_WORKSPACE_REFERENCES) {
      dispatch({
        type: 'notice_changed',
        notice: `工作区引用最多 ${MAX_WORKSPACE_REFERENCES} 个，请先移除一个已选引用。`
      })
      return
    }
    dispatch({ type: 'notice_changed', notice: '' })
    onToggleReference(entry)
  }, [onToggleReference, references])

  const toggleSortDirection = useCallback(() => {
    setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
  }, [])

  return {
    path,
    entries: state.entries,
    visibleEntries,
    loading: state.loading,
    listError: state.listError,
    actionError: state.actionError,
    notice: state.notice,
    search,
    sortKey,
    sortDirection,
    confirmDelete: state.confirmDelete,
    deletingPath: state.deletingPath,
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
