import type { NativePreviewRequest } from './native-api'
import { downloadSlidesBlob, exportBaseName } from './slides-export-download'

export function createSlidesPdfExport(options: {
  snapshot(): NativePreviewRequest | undefined
  filename?: string
  preview(payload: NativePreviewRequest, signal: AbortSignal): Promise<ArrayBuffer>
  status(message: string): void
  download?: typeof downloadSlidesBlob
}) {
  let active: AbortController | undefined
  let disposed = false
  return {
    async run() {
      if (active || disposed) return
      const snapshot = options.snapshot()
      if (!snapshot) return
      const identity = JSON.stringify(snapshot)
      const controller = new AbortController()
      active = controller
      options.status('正在导出 PDF…')
      try {
        const bytes = await options.preview(JSON.parse(identity) as NativePreviewRequest, controller.signal)
        if (controller.signal.aborted) return
        if (JSON.stringify(options.snapshot()) !== identity) throw new Error('演示文稿或草稿已变化，请重新导出。')
        if (new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') throw new Error('PDF 渲染结果无效。')
        const download = options.download ?? downloadSlidesBlob
        download(new Blob([bytes], { type: 'application/pdf' }), exportBaseName(options.filename) + '.pdf')
        options.status('已导出 PDF。')
      } catch (error) {
        if (!controller.signal.aborted) options.status(error instanceof Error ? error.message : 'PDF 导出失败。')
      } finally { if (active === controller) active = undefined }
    },
    dispose() { disposed = true; active?.abort() },
  }
}
