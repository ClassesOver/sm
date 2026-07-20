import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MentionReference, SessionEntry } from '../types'
import { MessageContextBar } from './MessageContextBar'
import { SessionItem } from './SessionItem'

afterEach(cleanup)

describe('会话与消息上下文组件', () => {
  it('分发会话加载、归档请求、确认和取消动作', () => {
    const session: SessionEntry = {
      id: 7,
      name: '七月会话',
      thread_id: 'thread-7',
      write_date: '2026-07-20T08:00:00+08:00'
    }
    const onLoad = vi.fn()
    const onRequestArchive = vi.fn()
    const onConfirmArchive = vi.fn()
    const onCancelArchive = vi.fn()
    const renderItem = (confirmingArchive: boolean) => <SessionItem
      session={session}
      selected
      confirmingArchive={confirmingArchive}
      onLoad={onLoad}
      onRequestArchive={onRequestArchive}
      onConfirmArchive={onConfirmArchive}
      onCancelArchive={onCancelArchive}
    />
    const { rerender } = render(renderItem(false))

    fireEvent.click(screen.getByRole('button', { name: /^七月会话/ }))
    fireEvent.click(screen.getByRole('button', { name: '归档 七月会话' }))
    expect(onLoad).toHaveBeenCalledWith(7)
    expect(onRequestArchive).toHaveBeenCalledWith(7)

    rerender(renderItem(true))
    fireEvent.click(screen.getByRole('button', { name: '确认归档 七月会话' }))
    fireEvent.click(screen.getByRole('button', { name: '取消归档' }))
    expect(onConfirmArchive).toHaveBeenCalledWith(7)
    expect(onCancelArchive).toHaveBeenCalledOnce()
  })

  it('展示消息上下文状态并分发引用移除动作', () => {
    const mention: MentionReference = {
      id: 'record-1', token: 'token-1', resourceKey: 'record:res.partner:7',
      kind: 'record', action: 'edit', label: '上海客户', detail: '联系人 #7',
      model: 'res.partner', expiresAt: '2026-07-20T09:00:00+08:00', valid: false,
      pageAction: true
    }
    const onRemoveMention = vi.fn()
    const onRemoveMenuMention = vi.fn()

    render(<MessageContextBar
      mentions={[mention]}
      workspaceReferences={[{ id: 'file-1', path: '合同/甲.txt', name: '甲.txt', isDirectory: false }]}
      skills={[{ id: 'audit', name: '合同审计', description: '核对合同字段', valid: false }]}
      menuMention={{
        menuId: 1, actionId: 11, name: '客户', path: ['销售', '客户'],
        fullPath: '销售 / 客户', valid: false
      }}
      onRemoveMention={onRemoveMention}
      onRemoveMenuMention={onRemoveMenuMention}
    />)

    expect(screen.getByText('编辑')).toBeTruthy()
    expect(screen.getByLabelText('消息工作区引用')).toBeTruthy()
    expect(screen.getByLabelText('消息技能')).toBeTruthy()
    expect(screen.getAllByText('（已失效）')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: '移除引用 上海客户' }))
    fireEvent.click(screen.getByRole('button', { name: '移除菜单' }))
    expect(onRemoveMention).toHaveBeenCalledWith('record-1')
    expect(onRemoveMenuMention).toHaveBeenCalledOnce()
  })
})
