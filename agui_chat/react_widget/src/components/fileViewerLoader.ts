type FileViewerComponent = typeof import('@file-viewer/react-full')['FileViewer']
type FileViewerModule = { FileViewer: FileViewerComponent }

export type { FileViewerComponent, FileViewerModule }

export const FILE_VIEWER_SCRIPT_URL = '/agui_chat/static/lib/agui-chat-react/agui_file_viewer.12.0.8.8.10.js'
export const FILE_VIEWER_LOAD_TIMEOUT_MS = 15_000

const STATUS_ATTRIBUTE = 'data-agui-file-viewer-status'

declare global {
  interface Window {
    AguiFileViewerBundle?: FileViewerModule
  }
}

let viewerModulePromise: Promise<FileViewerModule> | undefined

export function loadProductionFileViewerBundle(): Promise<FileViewerModule> {
  if (window.AguiFileViewerBundle?.FileViewer) return Promise.resolve(window.AguiFileViewerBundle)

  let existing = document.querySelector<HTMLScriptElement>(`script[src="${FILE_VIEWER_SCRIPT_URL}"]`)
  if (existing && ['error', 'loaded'].includes(existing.getAttribute(STATUS_ATTRIBUTE) || '')) {
    existing.remove()
    existing = null
  }
  const script = existing || document.createElement('script')

  return new Promise((resolve, reject) => {
    let settled = false
    let timeout = 0
    const cleanup = () => {
      window.clearTimeout(timeout)
      script.removeEventListener('load', handleLoad)
      script.removeEventListener('error', handleError)
    }
    const succeed = (module: FileViewerModule) => {
      if (settled) return
      settled = true
      script.setAttribute(STATUS_ATTRIBUTE, 'loaded')
      cleanup()
      resolve(module)
    }
    const fail = (message: string) => {
      if (settled) return
      settled = true
      script.setAttribute(STATUS_ATTRIBUTE, 'error')
      cleanup()
      reject(new Error(message))
    }
    const handleLoad = () => {
      const module = window.AguiFileViewerBundle
      if (module?.FileViewer) succeed(module)
      else fail('文件查看器资源未正确注册')
    }
    const handleError = () => fail('无法加载文件查看器资源')

    script.addEventListener('load', handleLoad)
    script.addEventListener('error', handleError)
    timeout = window.setTimeout(() => fail('加载文件查看器资源超时'), FILE_VIEWER_LOAD_TIMEOUT_MS)
    if (!existing) {
      script.setAttribute(STATUS_ATTRIBUTE, 'loading')
      script.src = FILE_VIEWER_SCRIPT_URL
      script.async = true
      document.head.appendChild(script)
    }
  })
}

export function loadFileViewer(): Promise<FileViewerModule> {
  if (!viewerModulePromise) {
    viewerModulePromise = window.AguiFileViewerBundle?.FileViewer
      ? Promise.resolve(window.AguiFileViewerBundle)
      : import.meta.env.DEV
      ? import('@file-viewer/react-full')
      : loadProductionFileViewerBundle()
    void viewerModulePromise.catch(() => { viewerModulePromise = undefined })
  }
  return viewerModulePromise
}
