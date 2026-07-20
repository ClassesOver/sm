import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import type { WorkspaceEntry, WorkspaceReference } from '../types'
import {
  INITIAL_WORKSPACE_DIRECTORY_STATE,
  useWorkspaceDirectory,
  workspaceDirectoryReducer
} from './useWorkspaceDirectory'
import { useWorkspacePreview } from './useWorkspacePreview'

function entry(path: string, overrides: Partial<WorkspaceEntry> = {}): WorkspaceEntry {
  const name = path.split('/').pop() || path
  return {
    path,
    name,
    isDirectory: false,
    size: 100,
    mimeType: 'text/plain',
    modifiedAt: '2026-07-20T08:00:00+08:00',
    ...overrides
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

function runtimeWith(overrides: Record<string, unknown> = {}): ChatRuntime {
  return {
    listWorkspace: vi.fn(async () => []),
    readWorkspaceFile: vi.fn(async () => ({ blob: new Blob(['content']), mimeType: 'text/plain' })),
    downloadWorkspaceFile: vi.fn(async () => undefined),
    deleteWorkspaceEntry: vi.fn(async () => undefined),
    ...overrides
  } as unknown as ChatRuntime
}

let revokeObjectURL: ReturnType<typeof vi.fn>

beforeEach(() => {
  let urlId = 0
  revokeObjectURL = vi.fn()
  Object.defineProperties(URL, {
    createObjectURL: { configurable: true, value: vi.fn(() => `blob:workspace-${++urlId}`) },
    revokeObjectURL: { configurable: true, value: revokeObjectURL }
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('工作区状态', () => {
  it('目录 reducer 原子更新加载和删除状态', () => {
    const target = entry('待删.txt')
    const loading = workspaceDirectoryReducer(INITIAL_WORKSPACE_DIRECTORY_STATE, {
      type: 'load_started',
      preserve: false
    })
    expect(loading).toMatchObject({ entries: [], loading: true, listError: '' })

    const loaded = workspaceDirectoryReducer(loading, {
      type: 'load_succeeded',
      entries: [target]
    })
    const requested = workspaceDirectoryReducer(loaded, { type: 'delete_requested', entry: target })
    const deleting = workspaceDirectoryReducer(requested, { type: 'delete_started', path: target.path })
    expect(deleting).toMatchObject({ confirmDelete: target, deletingPath: target.path })

    expect(workspaceDirectoryReducer(deleting, {
      type: 'delete_succeeded',
      path: target.path
    })).toMatchObject({ entries: [], confirmDelete: null, deletingPath: '' })
  })

  it('预览只采用最后一次读取结果，并可按目录关闭', async () => {
    const first = deferred<{ blob: Blob; mimeType: string }>()
    const second = deferred<{ blob: Blob; mimeType: string }>()
    const runtime = runtimeWith({
      readWorkspaceFile: vi.fn((path: string) => path.endsWith('甲.txt') ? first.promise : second.promise)
    })
    const { result } = renderHook(() => useWorkspacePreview(runtime))
    const firstEntry = entry('资料/甲.txt')
    const secondEntry = entry('资料/乙.txt')

    act(() => { void result.current.openPreview(firstEntry) })
    act(() => { void result.current.openPreview(secondEntry) })
    await act(async () => second.resolve({ blob: new Blob(['second']), mimeType: 'text/plain' }))
    expect(result.current.preview).toMatchObject({ entry: secondEntry, status: 'ready', url: 'blob:workspace-1' })

    await act(async () => first.resolve({ blob: new Blob(['first']), mimeType: 'text/plain' }))
    expect(result.current.preview?.entry).toBe(secondEntry)

    act(() => result.current.closeRelatedPreview(entry('资料', { isDirectory: true })))
    expect(result.current.preview).toBeNull()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:workspace-1')
  })

  it('目录状态集中处理引用上限和删除刷新', async () => {
    const target = entry('待删.txt')
    const references: WorkspaceReference[] = Array.from({ length: 5 }, (_, index) => ({
      id: `reference-${index}`,
      path: `reference-${index}.txt`,
      name: `reference-${index}.txt`,
      isDirectory: false
    }))
    const runtime = runtimeWith({ listWorkspace: vi.fn(async () => [target]) })
    const onToggleReference = vi.fn()
    const onDeleted = vi.fn()
    const { result } = renderHook(() => useWorkspaceDirectory({
      runtime,
      threadId: 'thread-1',
      references,
      onToggleReference,
      onDeleted
    }))

    await waitFor(() => expect(result.current.entries).toEqual([target]))
    act(() => result.current.toggleReference(target))
    expect(result.current.notice).toContain('工作区引用最多 5 个')
    expect(onToggleReference).not.toHaveBeenCalled()

    act(() => result.current.requestDelete(target))
    await act(async () => result.current.remove())
    expect(runtime.deleteWorkspaceEntry).toHaveBeenCalledWith(target.path, false)
    expect(onDeleted).toHaveBeenCalledWith(target)
    expect(result.current.confirmDelete).toBeNull()
    expect(runtime.listWorkspace).toHaveBeenCalledTimes(2)
  })
})
