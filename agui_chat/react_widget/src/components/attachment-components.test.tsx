import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mergeLabels } from '../customization'
import type { AttachmentRef } from '../types'
import { AttachmentQueue, type UploadItem } from './AttachmentQueue'
import { MessageAttachments } from './MessageAttachments'

afterEach(cleanup)

const labels = mergeLabels()

describe('附件组件', () => {
  it('展示待发送附件状态并触发移除和清空', () => {
    const uploading: UploadItem = {
      localId: 'uploading-1',
      file: new File(['pending'], 'pending.txt', { type: 'text/plain' }),
      progress: 42,
      status: 'uploading'
    }
    const failed: UploadItem = {
      localId: 'failed-1',
      file: new File(['failed'], 'failed.pdf', { type: 'application/pdf' }),
      progress: 0,
      status: 'error',
      error: '上传失败'
    }
    const onClear = vi.fn()
    const onRemove = vi.fn()

    render(<AttachmentQueue
      items={[uploading, failed]}
      labels={labels}
      onClear={onClear}
      onRemove={onRemove}
    />)

    expect(screen.getByText('上传中 42%')).toBeTruthy()
    expect(screen.getByText('上传失败')).toBeTruthy()
    expect(screen.getByText('failed.pdf')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: `${labels.removeAttachment} ${uploading.file.name}` }))
    expect(onRemove).toHaveBeenCalledWith(uploading)
    fireEvent.click(screen.getByRole('button', { name: labels.clearAttachments }))
    expect(onClear).toHaveBeenCalledOnce()
  })

  it('通过统一回调预览图片和文档附件', () => {
    const image: AttachmentRef = {
      id: 'image/1', name: 'diagram.png', mimeType: 'image/png', size: 2048, modality: 'image'
    }
    const document: AttachmentRef = {
      id: 'document-1', name: 'contract.pdf', mimeType: 'application/pdf', size: 4096, modality: 'document'
    }
    const onPreview = vi.fn()

    render(<MessageAttachments attachments={[image, document]} labels={labels} onPreview={onPreview} />)

    expect(screen.getByRole('img', { name: image.name }).getAttribute('src')).toBe('/agui_chat/attachment/image%2F1')
    expect(screen.getByText('PDF 文档 · 4 KB')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: `${labels.filePreview}: ${image.name}` }))
    fireEvent.click(screen.getByRole('button', { name: `${labels.filePreview}: ${document.name}` }))
    expect(onPreview).toHaveBeenNthCalledWith(1, image)
    expect(onPreview).toHaveBeenNthCalledWith(2, document)
  })

  it('没有消息附件时不渲染容器', () => {
    const { container } = render(<MessageAttachments labels={labels} onPreview={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })
})
