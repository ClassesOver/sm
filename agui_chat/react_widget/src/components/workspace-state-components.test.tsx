import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { WorkspaceEntry } from '../types'
import { WorkspaceDeleteBar } from './WorkspaceDeleteBar'
import { WorkspaceListState } from './WorkspaceListState'

afterEach(cleanup)

const entry: WorkspaceEntry = {
  path: '合同/待删.txt', name: '待删.txt', isDirectory: false,
  size: 100, mimeType: 'text/plain', modifiedAt: '2026-07-20T08:00:00+08:00'
}

describe('工作区状态组件', () => {
  it('分发删除确认并锁定删除中操作', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const { rerender } = render(<WorkspaceDeleteBar entry={entry} deletingPath="" onConfirm={onConfirm} onCancel={onCancel} />)

    expect(screen.getByText('删除“合同/待删.txt”？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onCancel).toHaveBeenCalledOnce()

    rerender(<WorkspaceDeleteBar entry={entry} deletingPath={entry.path} onConfirm={onConfirm} onCancel={onCancel} />)
    expect((screen.getByRole('button', { name: '删除中…' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '取消' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('区分加载、空目录、无匹配结果和错误状态', () => {
    const { container, rerender } = render(<WorkspaceListState
      loading hasEntries={false} hasVisibleEntries={false} hasError={false} search=""
    />)
    expect(screen.getByRole('status', { name: '正在加载工作区' })).toBeTruthy()
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(5)

    rerender(<WorkspaceListState loading={false} hasEntries={false} hasVisibleEntries={false} hasError={false} search="" />)
    expect(screen.getByText('当前目录为空。')).toBeTruthy()

    rerender(<WorkspaceListState loading={false} hasEntries hasVisibleEntries={false} hasError={false} search="合同" />)
    expect(screen.getByText('没有匹配结果，请尝试其他名称。')).toBeTruthy()

    rerender(<WorkspaceListState loading={false} hasEntries={false} hasVisibleEntries={false} hasError search="" />)
    expect(container.firstChild).toBeNull()
  })
})
