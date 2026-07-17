import {
  ChevronRight, Download, Eye, File, Folder, RefreshCw, Trash2, X
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { WorkspaceEntry } from '../types'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import { cn } from '../lib'
import { AsidePanel } from './AsidePanel'

interface WorkspacePanelProps {
  runtime: ChatRuntime
  threadId: string
  onClose: () => void
}

function sizeLabel(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function WorkspacePanel({ runtime, threadId, onClose }: WorkspacePanelProps) {
  const [path, setPath] = useState('')
  const [entries, setEntries] = useState<WorkspaceEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<{ entry: WorkspaceEntry; url: string; text?: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<WorkspaceEntry | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setEntries(await runtime.listWorkspace(path))
    } catch (reason) {
      setEntries([])
      setError((reason as Error)?.message || '工作区加载失败。')
    } finally {
      setLoading(false)
    }
  }, [path, runtime])

  useEffect(() => { void load() }, [load, threadId])
  useEffect(() => () => {
    if (preview?.url) URL.revokeObjectURL(preview.url)
  }, [preview])

  const breadcrumbs = useMemo(() => {
    const parts = path ? path.split('/') : []
    return [{ label: '工作区', path: '' }, ...parts.map((part, index) => ({
      label: part,
      path: parts.slice(0, index + 1).join('/')
    }))]
  }, [path])

  const openPreview = async (entry: WorkspaceEntry) => {
    setError('')
    try {
      const file = await runtime.readWorkspaceFile(entry.path)
      const url = URL.createObjectURL(file.blob)
      let text: string | undefined
      if (file.mimeType.startsWith('text/') || file.mimeType.includes('json')) {
        text = await file.blob.text()
      }
      setPreview((current) => {
        if (current?.url) URL.revokeObjectURL(current.url)
        return { entry, url, text }
      })
    } catch (reason) {
      setError((reason as Error)?.message || '文件预览失败。')
    }
  }

  const remove = async (entry: WorkspaceEntry) => {
    setError('')
    try {
      await runtime.deleteWorkspaceEntry(entry.path, entry.isDirectory)
      setConfirmDelete(null)
      if (preview?.entry.path === entry.path) setPreview(null)
      await load()
    } catch (reason) {
      setError((reason as Error)?.message || '删除失败。')
    }
  }

  return <AsidePanel
    ariaLabel="聊天工作区"
    eyebrow="当前对话"
    title="工作区"
    icon={<Folder size={14} />}
    closeLabel="关闭工作区"
    onClose={onClose}
    actions={<button type="button" aria-label="刷新工作区" title="刷新工作区" disabled={loading} onClick={() => void load()}><RefreshCw size={15} className={cn(loading && 'animate-spin')} /></button>}
    className="agui-workspace-aside"
  >
    <div className="flex h-full min-h-0 flex-col">
      <nav className="flex min-h-10 flex-wrap items-center gap-1 border-b border-border px-3 py-2" aria-label="工作区路径">
        {breadcrumbs.map((item, index) => <span key={item.path || 'root'} className="inline-flex min-w-0 items-center gap-1">
          {index ? <ChevronRight size={12} className="text-muted" /> : null}
          <button type="button" className="max-w-36 truncate border-0 bg-transparent p-0 text-xs text-secondary hover:text-primary" title={item.label} onClick={() => { setPath(item.path); setPreview(null) }}>{item.label}</button>
        </span>)}
      </nav>
      {error ? <div role="alert" className="border-b border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">{error}</div> : null}
      {preview ? <section className="flex min-h-0 flex-1 flex-col">
        <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
          <File size={14} className="text-muted" />
          <strong className="min-w-0 flex-1 truncate text-xs" title={preview.entry.name}>{preview.entry.name}</strong>
          <button type="button" className="grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary" aria-label="关闭预览" onClick={() => setPreview(null)}><X size={14} /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto bg-background p-3">
          {preview.text !== undefined ? <pre className="m-0 whitespace-pre-wrap break-words text-xs leading-5 text-secondary">{preview.text}</pre>
            : preview.entry.mimeType && preview.entry.mimeType.startsWith('image/') ? <img src={preview.url} alt={preview.entry.name} className="mx-auto block max-h-full max-w-full object-contain" />
              : preview.entry.mimeType === 'application/pdf' ? <iframe src={preview.url} title={preview.entry.name} className="h-full min-h-96 w-full border-0" />
                : <div className="grid h-full place-items-center text-xs text-muted">此文件可下载，但不支持内嵌预览。</div>}
        </div>
      </section> : <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? Array.from({ length: 5 }).map((_, index) => <div key={index} className="flex h-12 animate-pulse items-center gap-3 border-b border-border/60 px-3"><span className="size-6 bg-background-secondary"/><span className="h-3 flex-1 bg-background-secondary"/></div>) : null}
        {!loading && entries.map((entry) => <div key={entry.path} className="flex min-h-12 items-center gap-2 border-b border-border/60 px-3 py-1.5 hover:bg-background-secondary/60">
          <span className="grid size-7 shrink-0 place-items-center text-muted">{entry.isDirectory ? <Folder size={16} /> : <File size={15} />}</span>
          <button type="button" className="min-w-0 flex-1 border-0 bg-transparent p-0 text-left" onClick={() => entry.isDirectory ? setPath(entry.path) : void openPreview(entry)}>
            <span className="block truncate text-xs text-primary" title={entry.name}>{entry.name}</span>
            <span className="block text-[10px] text-muted">{entry.isDirectory ? '目录' : `${sizeLabel(entry.size)} · 已同步`}</span>
          </button>
          {!entry.isDirectory ? <>
            <button type="button" className="grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary" aria-label={`预览 ${entry.name}`} title="预览" onClick={() => void openPreview(entry)}><Eye size={14} /></button>
            <button type="button" className="grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary" aria-label={`下载 ${entry.name}`} title="下载" onClick={() => void runtime.downloadWorkspaceFile(entry.path).catch((reason) => setError((reason as Error).message))}><Download size={14} /></button>
          </> : null}
          <button type="button" className="grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-destructive/10 hover:text-destructive" aria-label={`删除 ${entry.name}`} title="删除" onClick={() => setConfirmDelete(entry)}><Trash2 size={14} /></button>
        </div>)}
        {!loading && !entries.length ? <div className="grid h-40 place-items-center text-xs text-muted">工作区为空</div> : null}
      </div>}
      {confirmDelete ? <div className="flex min-h-12 items-center gap-2 border-t border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
        <span className="min-w-0 flex-1 truncate" title={confirmDelete.name}>删除“{confirmDelete.name}”？</span>
        <button type="button" className="h-7 border border-warning/40 bg-background-panel px-2" onClick={() => void remove(confirmDelete)}>确认</button>
        <button type="button" className="h-7 border border-border bg-background-panel px-2" onClick={() => setConfirmDelete(null)}>取消</button>
      </div> : null}
    </div>
  </AsidePanel>
}
