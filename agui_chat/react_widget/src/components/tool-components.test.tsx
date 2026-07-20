import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToolConfirmationPreview } from './ToolConfirmationPreview'
import { ToolStatusBadge } from './ToolStatusBadge'

function importPreview(state = 'preview', revision = 1) {
  return {
    kind: 'x2many_import',
    import: {
      jobToken: 'job-1',
      state,
      revision,
      fileName: '明细.csv',
      fileSize: 128,
      rowCount: 2,
      previewRowCount: 2,
      headers: ['产品', '数量'],
      columns: [
        { index: 0, header: '产品', mappedField: 'name', mappable: true },
        { index: 1, header: '数量', mappedField: 'quantity', mappable: true }
      ],
      rows: [['很长的产品名称', '2'], ['第二项', '3']],
      parseOptions: { encoding: 'utf-8', separator: ',', quoting: '"' },
      errors: [],
      mappingHash: 'b'.repeat(64),
      result: state === 'done' ? { created: 2 } : {},
      target: { model: 'test.document', resId: 7, field: 'line_ids' },
      schema: {
        fields: [
          { name: 'name', label: '产品', type: 'char', required: true },
          { name: 'quantity', label: '数量', type: 'integer', required: false }
        ]
      }
    }
  }
}

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

  it('展示规范化导入表格并提交格式选项和映射', async () => {
    const onSubmit = vi.fn(async (request) => ({
      ok: true,
      jobToken: 'job-1',
      state: 'ready',
      revision: 2,
      preview: importPreview('ready', 2)
    }))
    render(<ToolConfirmationPreview
      result={{ preview: importPreview() }}
      onPreviewX2ManyImport={onSubmit}
    />)

    expect(screen.getByText('明细.csv')).toBeTruthy()
    expect(screen.getByText('很长的产品名称')).toBeTruthy()
    const nameMapping = screen.getByLabelText('映射 产品') as HTMLSelectElement
    const quantityMapping = screen.getByLabelText('映射 数量') as HTMLSelectElement
    expect(nameMapping.value).toBe('name')
    expect(quantityMapping.querySelector('option[value="name"]')?.hasAttribute('disabled')).toBe(true)

    fireEvent.change(screen.getByLabelText('分隔符'), { target: { value: ';' } })
    fireEvent.change(quantityMapping, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '测试导入' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce())
    expect(onSubmit.mock.calls[0][0]).toEqual({
      jobToken: 'job-1',
      expectedRevision: 1,
      parseOptions: { encoding: 'utf-8', separator: ';', quoting: '"' },
      mapping: { 产品: 'name', 数量: false },
      finalize: true
    })
    await waitFor(() => expect(screen.getByText('已通过测试')).toBeTruthy())
    expect((screen.getByLabelText('映射 产品') as HTMLSelectElement).disabled).toBe(true)
  })

  it('缺少必填映射时阻止测试并展示分行错误', () => {
    const original = importPreview()
    const preview = {
      ...original,
      import: {
        ...original.import,
        columns: original.import.columns.map((column, index) =>
          index === 0 ? { ...column, mappedField: false } : column
        ),
        errors: [{ row: 2, code: 'invalid_value', errors: ['产品无效'] }],
        errorCount: 3,
        errorReport: '/agui_chat_import/error/job-1'
      }
    }
    const onSubmit = vi.fn()
    render(<ToolConfirmationPreview
      result={{ preview }}
      onPreviewX2ManyImport={onSubmit}
    />)

    expect(screen.getByText('请映射必填字段：产品')).toBeTruthy()
    expect(screen.getByText('第 2 行：产品无效')).toBeTruthy()
    expect(screen.getByRole('link', { name: '下载完整错误报告（共 3 项）' }).getAttribute('href')).toBe('/agui_chat_import/error/job-1')
    expect((screen.getByRole('button', { name: '测试导入' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('服务端状态变化后重载只读结果', () => {
    const { rerender } = render(<ToolConfirmationPreview
      result={{ preview: importPreview('ready', 2) }}
    />)

    expect(screen.getByText('已通过测试')).toBeTruthy()
    rerender(<ToolConfirmationPreview
      result={{ preview: importPreview('done', 2) }}
    />)

    expect(screen.getByText('已完成')).toBeTruthy()
    expect(screen.getByText('已创建 2 条明细。')).toBeTruthy()
  })
})
