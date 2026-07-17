import { useEffect, useState } from 'react'
import type { FileViewerProps } from '@file-viewer/react-full'

const SCRIPT_URL = '/agui_chat/static/lib/agui-chat-react/agui_file_viewer.12.0.8.0.0.js'

type FileViewerComponent = typeof import('@file-viewer/react-full')['FileViewer']
type FileViewerModule = { FileViewer: FileViewerComponent }

declare global {
  interface Window {
    AguiFileViewerBundle?: FileViewerModule
  }
}

let viewerModulePromise: Promise<FileViewerModule> | undefined

function loadProductionBundle(): Promise<FileViewerModule> {
  if (window.AguiFileViewerBundle?.FileViewer) return Promise.resolve(window.AguiFileViewerBundle)

  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_URL}"]`)
    const script = existing || document.createElement('script')
    const handleLoad = () => window.AguiFileViewerBundle?.FileViewer
      ? resolve(window.AguiFileViewerBundle)
      : reject(new Error('File viewer bundle did not register'))
    const handleError = () => reject(new Error('Unable to load file viewer bundle'))

    script.addEventListener('load', handleLoad, { once: true })
    script.addEventListener('error', handleError, { once: true })
    if (!existing) {
      script.src = SCRIPT_URL
      script.async = true
      document.head.appendChild(script)
    }
  })
}

function loadFileViewer(): Promise<FileViewerModule> {
  if (!viewerModulePromise) {
    viewerModulePromise = window.AguiFileViewerBundle?.FileViewer
      ? Promise.resolve(window.AguiFileViewerBundle)
      : import.meta.env.DEV
      ? import('@file-viewer/react-full')
      : loadProductionBundle()
    viewerModulePromise.catch(() => { viewerModulePromise = undefined })
  }
  return viewerModulePromise
}

export function LazyFileViewer({ errorLabel, ...props }: FileViewerProps & { errorLabel: string }) {
  const [Viewer, setViewer] = useState<FileViewerComponent | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    loadFileViewer().then(
      (module) => { if (active) setViewer(() => module.FileViewer) },
      () => { if (active) setFailed(true) }
    )
    return () => { active = false }
  }, [])

  if (failed) {
    return <div className="agui-file-viewer-state text-sm text-muted" role="alert">{errorLabel}</div>
  }
  if (!Viewer) {
    return <div className="agui-file-viewer-state" aria-label="正在加载文件预览">
      <span className="agui-activity flex gap-1" aria-hidden="true">
        <span className="agui-activity-dot" />
        <span className="agui-activity-dot" />
        <span className="agui-activity-dot" />
      </span>
    </div>
  }
  return <Viewer {...props} />
}
