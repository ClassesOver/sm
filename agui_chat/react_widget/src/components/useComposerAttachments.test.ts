import { useRef } from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AttachmentRef } from '../types'
import { useComposerAttachments } from './useComposerAttachments'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

function useAttachmentHarness(
  onUpload: (file: File, onProgress: (progress: number) => void) => Promise<AttachmentRef>,
  onRemove = vi.fn(async () => undefined),
  attachments: boolean | Record<string, number> = true
) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  return useComposerAttachments({ attachments, disabled: false, textareaRef, onUpload, onRemove })
}

describe('消息输入附件状态', () => {
  it('跟踪上传进度并删除已上传附件', async () => {
    const upload = deferred<AttachmentRef>()
    let reportProgress: ((progress: number) => void) | undefined
    const onUpload = vi.fn((_file: File, onProgress: (progress: number) => void) => {
      reportProgress = onProgress
      return upload.promise
    })
    const onRemove = vi.fn(async () => undefined)
    const { result } = renderHook(() => useAttachmentHarness(onUpload, onRemove))
    const file = new File(['content'], 'report.txt', { type: 'text/plain' })

    act(() => result.current.addFiles([file]))
    expect(result.current.items[0]).toMatchObject({ file, progress: 0, status: 'uploading' })
    act(() => reportProgress?.(45))
    expect(result.current.items[0].progress).toBe(45)

    await act(async () => upload.resolve({
      id: 'attachment-1', name: file.name, mimeType: file.type, size: file.size, modality: 'document'
    }))
    expect(result.current.items[0]).toMatchObject({ progress: 100, status: 'ready' })
    expect(result.current.readyAttachments).toHaveLength(1)

    act(() => result.current.removeItem(result.current.items[0]))
    expect(result.current.items).toHaveLength(0)
    expect(onRemove).toHaveBeenCalledWith('attachment-1')
  })

  it('应用附件限制并在重置时释放图片预览', async () => {
    const createObjectURL = vi.fn(() => 'blob:image-1')
    const revokeObjectURL = vi.fn()
    Object.defineProperties(URL, {
      createObjectURL: { configurable: true, value: createObjectURL },
      revokeObjectURL: { configurable: true, value: revokeObjectURL }
    })
    const onUpload = vi.fn(async (file: File): Promise<AttachmentRef> => ({
      id: file.name, name: file.name, mimeType: file.type, size: file.size, modality: 'image'
    }))
    const { result, unmount } = renderHook(() => useAttachmentHarness(onUpload, undefined, { maxFiles: 1 }))
    const image = new File(['image'], 'preview.png', { type: 'image/png' })
    const extra = new File(['extra'], 'extra.txt', { type: 'text/plain' })

    await act(async () => result.current.addFiles([image, extra]))
    expect(result.current.items[1].error).toBe('最多添加 1 个文件')
    expect(onUpload).toHaveBeenCalledTimes(1)
    expect(createObjectURL).toHaveBeenCalledWith(image)

    act(() => result.current.resetItems())
    expect(result.current.items).toHaveLength(0)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:image-1')
    unmount()
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
  })
})
