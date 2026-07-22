import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mergeIcons, mergeLabels } from '../customization'
import { AssistantMessageControls } from './AssistantMessageControls'
import { MessageReasoning } from './MessageReasoning'
import { MessageReferences } from './MessageReferences'
import { SuggestionList } from './SuggestionList'

afterEach(cleanup)

describe('消息附属内容组件', () => {
  it('按顺序展示推理步骤并支持空列表', () => {
    const { container, rerender } = render(<MessageReasoning steps={[
      { title: '读取表单', content: '确认当前客户字段。' },
      { title: '生成建议' }
    ]} />)

    expect(screen.getByText('执行状态')).toBeTruthy()
    expect(screen.getByText('步骤 1：读取表单')).toBeTruthy()
    expect(screen.getByText('确认当前客户字段。')).toBeTruthy()
    expect(screen.getByText('步骤 2：生成建议')).toBeTruthy()

    rerender(<MessageReasoning steps={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('区分外链和无链接引用并支持空列表', () => {
    const { container, rerender } = render(<MessageReferences references={[{
      query: '合同',
      references: [
        { name: '外部文档', url: 'https://example.com/document', content: '合同摘要' },
        { name: '内部记录', content: '客户记录摘要' }
      ]
    }]} />)

    const link = screen.getByRole('link', { name: /外部文档/ })
    expect(link.getAttribute('href')).toBe('https://example.com/document')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(screen.getByText('内部记录').closest('a')).toBeNull()

    rerender(<MessageReferences references={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('仅为安全协议和同源绝对路径生成引用链接', () => {
    render(<MessageReferences references={[{
      query: '协议校验',
      references: [
        { name: 'HTTPS 文档', url: 'https://example.com/secure' },
        { name: 'HTTP 文档', url: 'http://example.com/local' },
        { name: '同源文档', url: '/web#id=7' },
        { name: '脚本协议', url: 'javascript:alert(1)' },
        { name: '数据协议', url: 'data:text/html,<script>alert(1)</script>' },
        { name: '协议相对地址', url: '//evil.example/path' },
        { name: '反斜杠地址', url: '/\\evil.example/path' },
        { name: '无效地址', url: 'not a url' }
      ]
    }]} />)

    expect(screen.getByRole('link', { name: /HTTPS 文档/ }).getAttribute('href')).toBe('https://example.com/secure')
    expect(screen.getByRole('link', { name: /HTTP 文档/ }).getAttribute('href')).toBe('http://example.com/local')
    expect(screen.getByRole('link', { name: /同源文档/ }).getAttribute('href')).toBe('/web#id=7')
    expect(screen.getAllByRole('link')).toHaveLength(3)
    for (const name of ['脚本协议', '数据协议', '协议相对地址', '反斜杠地址', '无效地址']) {
      expect(screen.getByText(name).closest('a')).toBeNull()
    }
  })

  it('展示建议并遵守禁用状态', () => {
    const suggestion = { title: '检查当前记录', message: '分析表单中的必填字段' }
    const onSelect = vi.fn()
    const { rerender } = render(<SuggestionList suggestions={[suggestion]} disabled onSelect={onSelect} />)

    const button = screen.getByRole('button', { name: /检查当前记录/ })
    fireEvent.click(button)
    expect(onSelect).not.toHaveBeenCalled()

    rerender(<SuggestionList suggestions={[suggestion]} disabled={false} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /检查当前记录/ }))
    expect(onSelect).toHaveBeenCalledWith(suggestion)
  })

  it('管理助手消息复制反馈和重新生成状态', async () => {
    const labels = mergeLabels()
    const icons = mergeIcons()
    const onCopy = vi.fn(async () => undefined)
    const onRegenerate = vi.fn()
    const { container, rerender } = render(<AssistantMessageControls
      isCurrent running={false} canRegenerate labels={labels} icons={icons}
      onCopy={onCopy} onRegenerate={onRegenerate}
    />)

    expect(container.firstElementChild?.className).toContain('opacity-100')
    fireEvent.click(screen.getByRole('button', { name: labels.copyResponse }))
    await waitFor(() => expect(screen.getByRole('button', { name: labels.copied })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: labels.regenerateResponse }))
    expect(onCopy).toHaveBeenCalledOnce()
    expect(onRegenerate).toHaveBeenCalledOnce()

    rerender(<AssistantMessageControls
      isCurrent={false} running canRegenerate labels={labels} icons={icons}
      onCopy={onCopy} onRegenerate={onRegenerate}
    />)
    expect((screen.getByRole('button', { name: labels.regenerateResponse }) as HTMLButtonElement).disabled).toBe(true)
  })
})
