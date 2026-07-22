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

  it('展示导出目标、范围、格式、记录数和有序列', () => {
    render(<ToolConfirmationPreview result={{
      preview: {
        export: {
          workspacePath: 'exports/hr.employee-20260722T010203Z-call1.csv',
          format: 'csv',
          scope: 'selection',
          recordCount: 2,
          fieldCount: 2,
          columns: ['姓名', '部门']
        }
      }
    }} />)

    expect(screen.getByText('exports/hr.employee-20260722T010203Z-call1.csv')).toBeTruthy()
    expect(screen.getByText('已选记录')).toBeTruthy()
    expect(screen.getByText('CSV')).toBeTruthy()
    expect(screen.getByText('2', { selector: 'span' })).toBeTruthy()
    expect(screen.getByText('姓名、部门')).toBeTruthy()
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
