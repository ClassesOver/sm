import { type ReactNode, useEffect, useState } from 'react'
import type { FileViewerProps } from '@file-viewer/react-full'
import { loadFileViewer, type FileViewerComponent } from './fileViewerLoader'
import { RenderErrorBoundary } from './RenderErrorBoundary'

interface LazyFileViewerProps extends FileViewerProps {
  errorLabel: string
  fallback?: ReactNode
}

type FileViewerLoadState =
  | { status: 'loading' }
  | { status: 'ready'; Viewer: FileViewerComponent }
  | { status: 'error' }

export function LazyFileViewer({ errorLabel, fallback, ...props }: LazyFileViewerProps) {
  const [loadState, setLoadState] = useState<FileViewerLoadState>({ status: 'loading' })
  const errorFallback = fallback || <div className="agui-file-viewer-state text-sm text-muted" role="alert">{errorLabel}</div>

  useEffect(() => {
    let active = true
    loadFileViewer().then(
      (module) => { if (active) setLoadState({ status: 'ready', Viewer: module.FileViewer }) },
      () => { if (active) setLoadState({ status: 'error' }) }
    )
    return () => { active = false }
  }, [])

  if (loadState.status === 'error') return errorFallback
  if (loadState.status === 'loading') {
    return <div className="agui-file-viewer-state" aria-label="正在加载文件预览">
      <span className="agui-activity flex gap-1" aria-hidden="true">
        <span className="agui-activity-dot" />
        <span className="agui-activity-dot" />
        <span className="agui-activity-dot" />
      </span>
    </div>
  }
  const Viewer = loadState.Viewer
  return <RenderErrorBoundary fallback={errorFallback} resetKeys={[Viewer, props.url]}>
    <Viewer {...props} />
  </RenderErrorBoundary>
}
