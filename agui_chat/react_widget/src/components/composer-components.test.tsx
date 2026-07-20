import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mergeIcons, mergeLabels } from '../customization'
import { ComposerContextBar } from './ComposerContextBar'
import { ComposerToolbar } from './ComposerToolbar'

afterEach(cleanup)

const labels = mergeLabels()
const icons = mergeIcons()

describe('消息输入组件', () => {
  it('展示三类上下文并触发对应移除回调', () => {
    const onRemoveWorkspaceReference = vi.fn()
    const onRemoveSkill = vi.fn()
    const onRemoveMenuMention = vi.fn()

    render(<ComposerContextBar
      workspaceReferences={[{ id: 'file-1', path: '合同/甲.txt', name: '甲.txt', isDirectory: false }]}
      selectedSkills={[{ id: 'audit', name: '合同审计', description: '核对合同字段', valid: false }]}
      menuMention={{
        menuId: 1, actionId: 11, name: '客户', path: ['销售', '客户'],
        fullPath: '销售 / 客户', valid: true
      }}
      onRemoveWorkspaceReference={onRemoveWorkspaceReference}
      onRemoveSkill={onRemoveSkill}
      onRemoveMenuMention={onRemoveMenuMention}
    />)

    expect(screen.getByText('（不可用）')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '移除工作区引用 甲.txt' }))
    fireEvent.click(screen.getByRole('button', { name: '移除技能 合同审计' }))
    fireEvent.click(screen.getByRole('button', { name: '移除菜单' }))
    expect(onRemoveWorkspaceReference).toHaveBeenCalledWith('file-1')
    expect(onRemoveSkill).toHaveBeenCalledWith('audit')
    expect(onRemoveMenuMention).toHaveBeenCalledOnce()
  })

  it('统一分发工具栏动作和表单提交', () => {
    const onAddAttachments = vi.fn()
    const onToggleSkills = vi.fn()
    const onOpenWorkspace = vi.fn()
    const onStop = vi.fn()
    const onSubmit = vi.fn()
    const toolbar = (running: boolean) => <ComposerToolbar
      attachmentsEnabled
      skillsEnabled
      disabled={false}
      sending={false}
      running={running}
      canSend
      skillOpen
      labels={labels}
      icons={icons}
      onAddAttachments={onAddAttachments}
      onToggleSkills={onToggleSkills}
      onOpenWorkspace={onOpenWorkspace}
      onStop={onStop}
    />
    const { rerender } = render(<form onSubmit={(event) => { event.preventDefault(); onSubmit() }}>{toolbar(false)}</form>)

    fireEvent.click(screen.getByRole('button', { name: labels.addAttachments }))
    fireEvent.click(screen.getByRole('button', { name: '选择技能' }))
    fireEvent.click(screen.getByRole('button', { name: '打开工作区' }))
    fireEvent.click(screen.getByRole('button', { name: labels.sendMessage }))
    expect(onAddAttachments).toHaveBeenCalledOnce()
    expect(onToggleSkills).toHaveBeenCalledOnce()
    expect(onOpenWorkspace).toHaveBeenCalledOnce()
    expect(onSubmit).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: '选择技能' }).getAttribute('aria-pressed')).toBe('true')

    rerender(<form onSubmit={(event) => { event.preventDefault(); onSubmit() }}>{toolbar(true)}</form>)
    fireEvent.click(screen.getByRole('button', { name: labels.stopGenerating }))
    expect(onStop).toHaveBeenCalledOnce()
    expect(onSubmit).toHaveBeenCalledOnce()
  })
})
