import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceBreadcrumbs } from './WorkspaceBreadcrumbs'

afterEach(cleanup)

describe('工作区面包屑', () => {
  it('构建完整路径并分发根目录和中间层导航', () => {
    const onNavigate = vi.fn()
    render(<WorkspaceBreadcrumbs path="合同/2026/七月" onNavigate={onNavigate} />)

    expect(screen.getByRole('navigation', { name: '工作区路径' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '工作区' }))
    fireEvent.click(screen.getByRole('button', { name: '2026' }))
    fireEvent.click(screen.getByRole('button', { name: '七月' }))
    expect(onNavigate).toHaveBeenNthCalledWith(1, '')
    expect(onNavigate).toHaveBeenNthCalledWith(2, '合同/2026')
    expect(onNavigate).toHaveBeenNthCalledWith(3, '合同/2026/七月')
  })
})
