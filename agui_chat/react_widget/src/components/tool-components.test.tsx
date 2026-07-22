import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ToolConfirmationPreview } from './ToolConfirmationPreview'
import { ToolStatusBadge } from './ToolStatusBadge'

afterEach(cleanup)

describe('工具展示组件', () => {
  it('展示字段差异和风险标签', () => {
    render(<ToolConfirmationPreview result={{
      preview: {
        changes: [{ field: 'name', label: '客户名称', oldValue: false, newValue: '上海客户' }],
        riskReasons: ['multiple_fields', 'custom_reason']
      }
    }} />)

    expect(screen.getByText('客户名称')).toBeTruthy()
    expect(screen.getByText('空')).toBeTruthy()
    expect(screen.getByText('上海客户')).toBeTruthy()
    expect(screen.getByText('多字段修改')).toBeTruthy()
    expect(screen.getByText('custom_reason')).toBeTruthy()
  })

  it('统一工具状态标签和颜色', () => {
    const { container, rerender } = render(<ToolStatusBadge status="running" />)
    expect(screen.getByText('执行中')).toBeTruthy()
    expect(container.querySelector('.animate-spin')).toBeTruthy()

    rerender(<ToolStatusBadge status="ok" />)
    expect(screen.getByText('已完成')).toBeTruthy()
    expect(container.firstElementChild?.className).toContain('text-positive')

    rerender(<ToolStatusBadge status="error" />)
    expect(screen.getByText('出错')).toBeTruthy()
    expect(container.firstElementChild?.className).toContain('text-destructive')
  })
})
