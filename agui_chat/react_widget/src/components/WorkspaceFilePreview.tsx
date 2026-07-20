import { Download, File, X } from 'lucide-react'
import type { WorkspaceEntry } from '../types'
import { Button } from './Button'
import { IconButton } from './IconButton'
import { LazyFileViewer } from './LazyFileViewer'
import type { WorkspacePreviewState } from './useWorkspaceState'

export type { WorkspacePreviewState } from './useWorkspaceState'

interface WorkspaceFilePreviewProps {
  preview: WorkspacePreviewState
  onDownload: (entry: WorkspaceEntry) => void
  onClose: () => void
}

export function WorkspaceFilePreview({ preview, onDownload, onClose }: WorkspaceFilePreviewProps) {
  const fallback = <div className="grid h-full content-center justify-items-center gap-3 p-6 text-center text-xs text-muted" role="alert">
    <p className="m-0">{preview.status === 'error'
      ? preview.error
      : preview.status === 'unsupported'
        ? '此格式暂不支持在线预览，请下载后查看。'
        : '文件查看器加载失败，请下载后查看。'}</p>
    <Button size="sm" className="h-8 rounded-md bg-background-panel text-secondary" onClick={() => onDownload(preview.entry)}>
      <Download size={14} />下载文件
    </Button>
  </div>

  return <section className="flex min-h-0 flex-1 flex-col">
    <header className="flex min-h-10 shrink-0 items-center gap-2 border-b border-border px-3">
      <File size={14} className="text-muted" />
      <strong className="min-w-0 flex-1 truncate text-xs" title={preview.entry.path}>{preview.entry.name}</strong>
      {!preview.entry.isDirectory ? <IconButton label={`下载 ${preview.entry.name}`} title="下载" onClick={() => onDownload(preview.entry)}><Download size={14} /></IconButton> : null}
      <IconButton label="关闭预览" onClick={onClose}><X size={14} /></IconButton>
    </header>
    <div className="min-h-0 flex-1 overflow-auto bg-background">
      {preview.status === 'loading' ? <div className="grid h-full place-items-center text-xs text-muted" role="status">正在读取文件预览…</div>
        : preview.status === 'ready' && preview.url && preview.type ? <LazyFileViewer
          key={`${preview.entry.path}:${preview.url}`}
          className="agui-file-viewer"
          errorLabel="文件查看器加载失败"
          fallback={fallback}
          url={preview.url}
          filename={preview.entry.name}
          name={preview.entry.name}
          type={preview.type}
          options={{ theme: 'light', styleIsolation: 'shadow' }}
        />
          : fallback}
    </div>
  </section>
}
