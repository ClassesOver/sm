import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FileViewerProps } from '@file-viewer/react-full'

const loader = vi.hoisted(() => ({ loadFileViewer: vi.fn() }))

vi.mock('./fileViewerLoader', () => loader)

import { LazyFileViewer } from './LazyFileViewer'

afterEach(() => {
  cleanup()
  loader.loadFileViewer.mockReset()
})

describe('延迟文件查看器', () => {
  it('从加载状态进入就绪状态', async () => {
    const Viewer = ({ url }: FileViewerProps) => <div>已加载 {url}</div>
    loader.loadFileViewer.mockResolvedValue({ FileViewer: Viewer })

    render(<LazyFileViewer url="blob:file-1" errorLabel="加载失败" />)
    expect(screen.getByLabelText('正在加载文件预览')).toBeTruthy()
    expect(await screen.findByText('已加载 blob:file-1')).toBeTruthy()
  })

  it('加载失败后只展示回退状态', async () => {
    loader.loadFileViewer.mockRejectedValue(new Error('资源失败'))

    render(<LazyFileViewer url="blob:file-2" errorLabel="加载失败" />)
    expect((await screen.findByRole('alert')).textContent).toContain('加载失败')
    expect(screen.queryByLabelText('正在加载文件预览')).toBeNull()
  })
})
