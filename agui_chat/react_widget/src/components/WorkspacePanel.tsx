import {
  ArrowDown, ArrowUp, Check, ChevronRight, Download, Eye, File, Folder,
  MessageSquarePlus, RefreshCw, Search, Trash2, X
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { WorkspaceEntry, WorkspaceReference } from '../types'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import { cn } from '../lib'
import { AsidePanel } from './AsidePanel'
import { IconButton } from './IconButton'
import { canPreviewFile, getFilePreviewType } from './filePreviewType'
import { LazyFileViewer } from './LazyFileViewer'

interface WorkspacePanelProps {
  runtime: ChatRuntime
  threadId: string
  references: WorkspaceReference[]
  onToggleReference: (entry: WorkspaceEntry) => void
  onDeleted: (entry: WorkspaceEntry) => void
  onClose: () => void
}

type SortKey = 'name' | 'modifiedAt' | 'size'
type SortDirection = 'asc' | 'desc'
type PreviewState = {
  entry: WorkspaceEntry
  status: 'loading' | 'ready' | 'error' | 'unsupported'
  url?: string
  type?: string
  error?: string
}

const MAX_REFERENCES = 5
const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
const modifiedAtFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
})

function sizeLabel(size: number): string {
  if (!Number.isFinite(size) || size < 0) return '大小未知'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatModifiedAt(value: string): string {
  const date = new Date(value)
  if (!value || !Number.isFinite(date.getTime())) return '时间未知'
  return modifiedAtFormatter.format(date)
}

function fileTypeLabel(entry: WorkspaceEntry): string {
  if (entry.isDirectory) return '目录'
  const type = getFilePreviewType(entry.name, entry.mimeType)
  if (!type || type.includes('/')) return '文件'
  return type.replace('+xml', '').toUpperCase()
}

function compareEntries(left: WorkspaceEntry, right: WorkspaceEntry, key: SortKey, direction: SortDirection): number {
  if (left.isDirectory !== right.isDirectory) return left.isDirectory ? -1 : 1

  let result = 0
  if (key === 'name') {
    result = collator.compare(left.name, right.name)
  } else if (key === 'size') {
    const leftSize = Number.isFinite(left.size) ? left.size : 0
    const rightSize = Number.isFinite(right.size) ? right.size : 0
    result = leftSize - rightSize
  } else {
    const leftTime = new Date(left.modifiedAt).getTime()
    const rightTime = new Date(right.modifiedAt).getTime()
    const leftValid = Number.isFinite(leftTime)
    const rightValid = Number.isFinite(rightTime)
    if (leftValid !== rightValid) return leftValid ? -1 : 1
    if (leftValid && rightValid) result = leftTime - rightTime
  }

  if (result === 0) result = collator.compare(left.name, right.name)
  return direction === 'asc' ? result : -result
}

function sortWorkspaceEntries(entries: WorkspaceEntry[], key: SortKey, direction: SortDirection): WorkspaceEntry[] {
  return [...entries].sort((left, right) => compareEntries(left, right, key, direction))
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback
}

function isInside(entry: WorkspaceEntry, path: string): boolean {
  return entry.path === path || (entry.isDirectory && path.startsWith(`${entry.path}/`))
}

export function WorkspacePanel({ runtime, threadId, references, onToggleReference, onDeleted, onClose }: WorkspacePanelProps) {
  const [path, setPath] = useState('')
  const [entries, setEntries] = useState<WorkspaceEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<WorkspaceEntry | null>(null)
  const [deletingPath, setDeletingPath] = useState('')
  const listRequest = useRef(0)
  const previewRequest = useRef(0)

  const closePreview = useCallback(() => {
    previewRequest.current += 1
    setPreview(null)
  }, [])

  useEffect(() => () => {
    listRequest.current += 1
    previewRequest.current += 1
  }, [])
  useEffect(() => {
    const url = preview?.url
    return () => { if (url) URL.revokeObjectURL(url) }
  }, [preview?.url])

  const load = useCallback(async (preserve = false) => {
    const request = ++listRequest.current
    setLoading(true)
    setListError('')
    if (!preserve) setEntries([])
    try {
      const nextEntries = await runtime.listWorkspace(path)
      if (request === listRequest.current) setEntries(nextEntries)
    } catch (reason) {
      if (request === listRequest.current) setListError(errorMessage(reason, '工作区加载失败，请重试。'))
    } finally {
      if (request === listRequest.current) setLoading(false)
    }
  }, [path, runtime])

  useEffect(() => { void load() }, [load, threadId])

  const navigate = (nextPath: string) => {
    setPath(nextPath)
    setSearch('')
    setConfirmDelete(null)
    setActionError('')
    setNotice('')
    closePreview()
  }

  const breadcrumbs = useMemo(() => {
    const parts = path ? path.split('/') : []
    return [{ label: '工作区', path: '' }, ...parts.map((part, index) => ({
      label: part,
      path: parts.slice(0, index + 1).join('/')
    }))]
  }, [path])

  const visibleEntries = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('zh-CN')
    const filtered = query
      ? entries.filter((entry) => entry.name.toLocaleLowerCase('zh-CN').includes(query))
      : entries
    return sortWorkspaceEntries(filtered, sortKey, sortDirection)
  }, [entries, search, sortDirection, sortKey])

  const openPreview = async (entry: WorkspaceEntry) => {
    const request = ++previewRequest.current
    setActionError('')
    setNotice('')
    setPreview({ entry, status: 'loading' })
    try {
      const file = await runtime.readWorkspaceFile(entry.path)
      if (request !== previewRequest.current) return
      const type = getFilePreviewType(entry.name, file.mimeType || entry.mimeType)
      if (!canPreviewFile(type)) {
        setPreview({ entry, status: 'unsupported', type })
        return
      }
      const url = URL.createObjectURL(file.blob)
      if (request !== previewRequest.current) {
        URL.revokeObjectURL(url)
        return
      }
      setPreview({ entry, status: 'ready', type, url })
    } catch (reason) {
      if (request === previewRequest.current) {
        setPreview({ entry, status: 'error', error: errorMessage(reason, '文件读取失败，请下载后查看。') })
      }
    }
  }

  const download = (entry: WorkspaceEntry) => {
    setActionError('')
    void runtime.downloadWorkspaceFile(entry.path).catch((reason) => {
      setActionError(errorMessage(reason, '文件下载失败，请重试。'))
    })
  }

  const remove = async () => {
    const entry = confirmDelete
    if (!entry || deletingPath) return
    setDeletingPath(entry.path)
    setActionError('')
    try {
      await runtime.deleteWorkspaceEntry(entry.path, entry.isDirectory)
      setEntries((current) => current.filter((candidate) => candidate.path !== entry.path))
      onDeleted(entry)
      if (preview && isInside(entry, preview.entry.path)) closePreview()
      setConfirmDelete(null)
      void load(true)
    } catch (reason) {
      setActionError(errorMessage(reason, '删除失败，请重试。'))
    } finally {
      setDeletingPath('')
    }
  }

  const toggleReference = (entry: WorkspaceEntry) => {
    const selected = references.some((item) => item.path === entry.path)
    if (!selected && references.length >= MAX_REFERENCES) {
      setNotice('工作区引用最多 5 个，请先移除一个已选引用。')
      return
    }
    setNotice('')
    onToggleReference(entry)
  }

  const fallback = preview ? <div className="grid h-full content-center justify-items-center gap-3 p-6 text-center text-xs text-muted" role="alert">
    <p className="m-0">{preview.status === 'error'
      ? preview.error
      : preview.status === 'unsupported'
        ? '此格式暂不支持在线预览，请下载后查看。'
        : '文件查看器加载失败，请下载后查看。'}</p>
    <button type="button" className="inline-flex h-8 items-center gap-1.5 border border-border bg-background-panel px-3 text-xs text-secondary hover:bg-accent hover:text-primary" onClick={() => download(preview.entry)}>
      <Download size={14} />下载文件
    </button>
  </div> : null

  return <AsidePanel
    ariaLabel="聊天工作区"
    eyebrow="当前对话"
    title="工作区"
    icon={<Folder size={14} />}
    closeLabel="关闭工作区"
    onClose={onClose}
    actions={<IconButton label="刷新工作区" size="md" variant="outline" disabled={loading} onClick={() => void load(true)}><RefreshCw size={15} className={cn(loading && 'animate-spin')} /></IconButton>}
    className="agui-workspace-aside"
  >
    <div className="flex h-full min-h-0 flex-col">
      <nav className="flex min-h-10 flex-wrap items-center gap-1 border-b border-border px-3 py-2" aria-label="工作区路径">
        {breadcrumbs.map((item, index) => <span key={item.path || 'root'} className="inline-flex min-w-0 items-center gap-1">
          {index ? <ChevronRight size={12} className="text-muted" /> : null}
          <button type="button" className="max-w-36 truncate border-0 bg-transparent p-0 text-xs text-secondary hover:text-primary" title={item.label} onClick={() => navigate(item.path)}>{item.label}</button>
        </span>)}
      </nav>
      {listError ? <div role="alert" className="flex items-center gap-2 border-b border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive"><span className="min-w-0 flex-1">{listError}</span><button type="button" className="shrink-0 border-0 bg-transparent p-0 font-medium underline" onClick={() => void load(entries.length > 0)}>重试</button></div> : null}
      {actionError ? <div role="alert" className="border-b border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">{actionError}</div> : null}
      {notice ? <div role="status" className="border-b border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{notice}</div> : null}
      {preview ? <section className="flex min-h-0 flex-1 flex-col">
        <header className="flex min-h-10 shrink-0 items-center gap-2 border-b border-border px-3">
          <File size={14} className="text-muted" />
          <strong className="min-w-0 flex-1 truncate text-xs" title={preview.entry.path}>{preview.entry.name}</strong>
          {!preview.entry.isDirectory ? <IconButton label={`下载 ${preview.entry.name}`} title="下载" onClick={() => download(preview.entry)}><Download size={14} /></IconButton> : null}
          <IconButton label="关闭预览" onClick={closePreview}><X size={14} /></IconButton>
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
      </section> : <>
        <div className="space-y-2 border-b border-border px-3 py-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <label className="flex min-w-0 flex-1 items-center gap-1.5 border border-border bg-background-panel px-2">
              <Search size={14} className="shrink-0 text-muted" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} className="h-8 min-w-0 flex-1 border-0 bg-transparent p-0 text-xs outline-none" placeholder="搜索当前目录" aria-label="搜索当前目录" />
              {search ? <IconButton label="清空搜索" size="xs" className="hover:bg-transparent" onClick={() => setSearch('')}><X size={13} /></IconButton> : null}
            </label>
            <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} className="h-8 w-24 shrink-0 border border-border bg-background-panel px-1.5 text-xs text-secondary" aria-label="排序方式">
              <option value="name">按名称</option>
              <option value="modifiedAt">按修改时间</option>
              <option value="size">按大小</option>
            </select>
            <IconButton label={sortDirection === 'asc' ? '切换为降序' : '切换为升序'} size="md" variant="outline" onClick={() => setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')}>
              {sortDirection === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
            </IconButton>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted" aria-live="polite">
            <span>当前结果 {visibleEntries.length} 项</span>
            <span>已选引用 {references.length}/{MAX_REFERENCES}</span>
            {loading && entries.length ? <span>正在刷新…</span> : null}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto" role="list" aria-label="工作区文件" aria-busy={loading}>
          {loading && !entries.length ? <div role="status" aria-label="正在加载工作区">{Array.from({ length: 5 }).map((_, index) => <div key={index} className="flex h-14 animate-pulse items-center gap-3 border-b border-border/60 px-3"><span className="size-6 bg-background-secondary"/><span className="h-3 flex-1 bg-background-secondary"/></div>)}</div> : null}
          {!loading && !listError && !visibleEntries.length ? <div className="grid h-40 place-items-center px-6 text-center text-xs text-muted">{search.trim() ? '没有匹配结果，请尝试其他名称。' : '当前目录为空。'}</div> : null}
          {visibleEntries.map((entry) => {
            const selected = references.some((item) => item.path === entry.path)
            const atLimit = !selected && references.length >= MAX_REFERENCES
            const deleting = Boolean(deletingPath)
            return <div key={entry.path} role="listitem" data-entry-name={entry.name} className="flex min-h-14 items-center gap-1.5 border-b border-border/60 px-3 py-1.5 hover:bg-background-secondary/60">
              <IconButton label={`${selected ? '移除' : '加入'}对话 ${entry.name}`} title={atLimit ? '工作区引用最多 5 个' : selected ? '移除引用' : '加入对话'} className={cn(selected && 'bg-accent text-primary')} aria-pressed={selected} onClick={() => toggleReference(entry)}>
                {selected ? <Check size={14} /> : <MessageSquarePlus size={14} />}
              </IconButton>
              <span className="grid size-7 shrink-0 place-items-center text-muted">{entry.isDirectory ? <Folder size={16} /> : <File size={15} />}</span>
              <button type="button" className="min-w-0 flex-1 border-0 bg-transparent p-0 text-left" onClick={() => entry.isDirectory ? navigate(entry.path) : void openPreview(entry)}>
                <span className="block truncate text-xs text-primary" title={entry.path}>{entry.name}</span>
                <span className="flex min-w-0 flex-wrap gap-x-2 text-[10px] text-muted"><span>{fileTypeLabel(entry)}</span>{!entry.isDirectory ? <span>{sizeLabel(entry.size)}</span> : null}<time dateTime={entry.modifiedAt} title={entry.modifiedAt || '时间未知'}>{formatModifiedAt(entry.modifiedAt)}</time></span>
              </button>
              {!entry.isDirectory ? <>
                <IconButton label={`预览 ${entry.name}`} title="预览" onClick={() => void openPreview(entry)}><Eye size={14} /></IconButton>
                <IconButton label={`下载 ${entry.name}`} title="下载" onClick={() => download(entry)}><Download size={14} /></IconButton>
              </> : null}
              <IconButton label={`删除 ${entry.name}`} title="删除" variant="danger" disabled={deleting} onClick={() => { setConfirmDelete(entry); setActionError('') }}><Trash2 size={14} /></IconButton>
            </div>
          })}
        </div>
      </>}
      {confirmDelete ? <div className="flex min-h-12 items-center gap-2 border-t border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
        <span className="min-w-0 flex-1 break-all" title={confirmDelete.path}>删除“{confirmDelete.path}”？</span>
        <button type="button" className="h-7 shrink-0 border border-warning/40 bg-background-panel px-2 disabled:cursor-not-allowed disabled:opacity-50" disabled={deletingPath === confirmDelete.path} onClick={() => void remove()}>{deletingPath === confirmDelete.path ? '删除中…' : '确认'}</button>
        <button type="button" className="h-7 shrink-0 border border-border bg-background-panel px-2 disabled:opacity-50" disabled={Boolean(deletingPath)} onClick={() => setConfirmDelete(null)}>取消</button>
      </div> : null}
    </div>
  </AsidePanel>
}
