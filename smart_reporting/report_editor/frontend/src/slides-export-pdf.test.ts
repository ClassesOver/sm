import { expect, it, vi } from 'vitest'
import { createSlidesPdfExport } from './slides-export-pdf'
import type { NativePreviewRequest } from './native-api'

it('downloads the PDF of the frozen draft without saving a revision', async () => {
  const draft: NativePreviewRequest = { expectedSha256: 'a'.repeat(64), operations: [{ kind: 'editSlides', order: [1, 0] }] }
  const preview = vi.fn(async () => new TextEncoder().encode('%PDF-1.7\n').buffer)
  const download = vi.fn(), status = vi.fn()
  const exporter = createSlidesPdfExport({ snapshot: () => draft, filename: '季度报告.pptx', preview, download, status })
  await exporter.run()
  expect(preview).toHaveBeenCalledWith(draft, expect.any(AbortSignal))
  expect(preview.mock.lastCall).toBeDefined()
  expect(download).toHaveBeenCalledWith(expect.objectContaining({ type: 'application/pdf' }), '季度报告.pdf')
  expect(status).toHaveBeenLastCalledWith('已导出 PDF。')
})

it('suppresses stale and non-PDF responses while keeping the source draft usable', async () => {
  const draft: NativePreviewRequest = { expectedSha256: 'a'.repeat(64), operations: [] }
  const download = vi.fn(), status = vi.fn()
  let release!: (bytes: ArrayBuffer) => void
  const preview = vi.fn(() => new Promise<ArrayBuffer>(resolve => { release = resolve }))
  const exporter = createSlidesPdfExport({ snapshot: () => draft, preview, download, status })
  const exporting = exporter.run()
  draft.operations.push({ kind: 'editSlides', order: [1, 0] })
  release(new TextEncoder().encode('%PDF-1.7\n').buffer)
  await exporting
  expect(download).not.toHaveBeenCalled()
  expect(status).toHaveBeenLastCalledWith('演示文稿或草稿已变化，请重新导出。')
  preview.mockResolvedValueOnce(new TextEncoder().encode('<html>').buffer)
  await exporter.run()
  expect(download).not.toHaveBeenCalled()
  expect(status).toHaveBeenLastCalledWith('PDF 渲染结果无效。')
})
