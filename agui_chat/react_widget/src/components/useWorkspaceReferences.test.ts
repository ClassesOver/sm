import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { WorkspaceEntry } from '../types'
import { MAX_WORKSPACE_REFERENCES, useWorkspaceReferences } from './useWorkspaceReferences'

afterEach(cleanup)

function entry(path: string, isDirectory = false): WorkspaceEntry {
  return {
    path,
    name: path.split('/').pop() || path,
    isDirectory,
    size: 0,
    mimeType: isDirectory ? false : 'text/plain',
    modifiedAt: ''
  }
}

describe('工作区引用状态', () => {
  it('切换引用并统一限制最多五项', () => {
    const { result } = renderHook(() => useWorkspaceReferences('thread-1'))
    const entries = Array.from({ length: MAX_WORKSPACE_REFERENCES + 1 }, (_, index) => entry(`文件-${index}.txt`))

    act(() => entries.forEach(result.current.toggleReference))
    expect(result.current.references).toHaveLength(MAX_WORKSPACE_REFERENCES)
    expect(result.current.references.some((item) => item.path === entries.at(-1)?.path)).toBe(false)

    act(() => result.current.toggleReference(entries[0]))
    expect(result.current.references).toHaveLength(MAX_WORKSPACE_REFERENCES - 1)
    act(() => result.current.removeReference(`workspace:${entries[1].path}`))
    expect(result.current.references.some((item) => item.path === entries[1].path)).toBe(false)
  })

  it('删除目录时清理子路径，并在线程切换时重置', () => {
    const { result, rerender } = renderHook(
      ({ threadId }) => useWorkspaceReferences(threadId),
      { initialProps: { threadId: 'thread-1' } }
    )
    const directory = entry('资料', true)
    const child = entry('资料/合同.txt')
    const other = entry('其他.txt')

    act(() => [directory, child, other].forEach(result.current.toggleReference))
    act(() => result.current.removeDeleted(directory))
    expect(result.current.references.map((item) => item.path)).toEqual(['其他.txt'])

    rerender({ threadId: 'thread-2' })
    expect(result.current.references).toEqual([])
  })
})
