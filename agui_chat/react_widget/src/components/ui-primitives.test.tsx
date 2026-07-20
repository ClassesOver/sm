import { createRef } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { X } from 'lucide-react'
import { CandidateOption, CandidatePanel } from './CandidatePanel'
import { ContextChip } from './ContextChip'
import { IconButton } from './IconButton'
import { InlineNotice } from './InlineNotice'
import { PickerSurface } from './PickerSurface'

describe('UI 基础组件', () => {
  it('图标按钮提供统一的名称、提示和尺寸', () => {
    const onClick = vi.fn()
    render(<IconButton label="关闭" size="md" variant="outline" onClick={onClick}><X size={14} /></IconButton>)

    const button = screen.getByRole('button', { name: '关闭' })
    expect(button.getAttribute('title')).toBe('关闭')
    expect(button.className).toContain('size-8')
    expect(button.className).toContain('border-border')
    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('选择器外壳统一 dialog 语义并透传 DOM 属性和 ref', () => {
    const ref = createRef<HTMLDivElement>()
    render(<PickerSurface ref={ref} ariaLabel="测试选择器" tabIndex={-1} data-testid="picker">内容</PickerSurface>)

    const picker = screen.getByRole('dialog', { name: '测试选择器' })
    expect(picker).toBe(ref.current)
    expect(picker.getAttribute('tabindex')).toBe('-1')
    expect(picker.className).toContain('agui-picker')
  })

  it('上下文标签统一状态和移除交互', () => {
    const onRemove = vi.fn()
    render(<ContextChip
      icon={<X size={12} />}
      label="合同审计"
      tone="warning"
      trailing={<span>（不可用）</span>}
      onRemove={onRemove}
      removeLabel="移除技能 合同审计"
    />)

    const remove = screen.getByRole('button', { name: '移除技能 合同审计' })
    expect(remove.parentElement?.className).toContain('border-warning')
    expect(screen.getByText('（不可用）')).toBeTruthy()
    fireEvent.click(remove)
    expect(onRemove).toHaveBeenCalledOnce()
  })

  it('候选面板统一空态和选项交互', () => {
    const onSelect = vi.fn()
    const { rerender } = render(<CandidatePanel title="客户" description="匹配记录" badge="选择" emptyMessage="没有候选" />)
    expect(screen.getByText('没有候选')).toBeTruthy()

    rerender(<CandidatePanel title="客户" description="匹配记录" badge="选择" emptyMessage="没有候选">
      <CandidateOption trailing={<span>#1</span>} onClick={onSelect}>上海客户</CandidateOption>
    </CandidatePanel>)
    fireEvent.click(screen.getByRole('button', { name: /上海客户/ }))
    expect(onSelect).toHaveBeenCalledOnce()
  })

  it('行内提示统一语义角色和布局变体', () => {
    render(<InlineNotice tone="error" variant="band">加载失败</InlineNotice>)
    const notice = screen.getByRole('alert')
    expect(notice.className).toContain('border-b')
    expect(notice.className).toContain('text-destructive')
  })
})
