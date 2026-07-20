import { Check, Download, Eye, File, Folder, MessageSquarePlus, Trash2 } from 'lucide-react'
import type { WorkspaceEntry } from '../types'
import { cn } from '../lib'
import { getFilePreviewType } from './filePreviewType'
import { IconButton } from './IconButton'

interface WorkspaceEntryRowProps {
  entry: WorkspaceEntry
  selected: boolean
  atReferenceLimit: boolean
  deleting: boolean
  onToggleReference: (entry: WorkspaceEntry) => void
  onOpen: (entry: WorkspaceEntry) => void
  onPreview: (entry: WorkspaceEntry) => void
  onDownload: (entry: WorkspaceEntry) => void
  onDelete: (entry: WorkspaceEntry) => void
}

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

export function WorkspaceEntryRow({
  entry, selected, atReferenceLimit, deleting,
  onToggleReference, onOpen, onPreview, onDownload, onDelete
}: WorkspaceEntryRowProps) {
  return <div role="listitem" data-entry-name={entry.name} className="group flex min-h-14 items-center gap-1.5 border-b border-border/45 px-3 py-1.5 transition-colors hover:bg-background-secondary/70 focus-within:bg-background-secondary/70">
    <IconButton label={`${selected ? '移除' : '加入'}对话 ${entry.name}`} title={atReferenceLimit ? '工作区引用最多 5 个' : selected ? '移除引用' : '加入对话'} className={cn(selected && 'bg-accent text-primary')} aria-pressed={selected} onClick={() => onToggleReference(entry)}>
      {selected ? <Check size={14} /> : <MessageSquarePlus size={14} />}
    </IconButton>
    <span className="grid size-7 shrink-0 place-items-center text-muted/90">{entry.isDirectory ? <Folder size={16} /> : <File size={15} />}</span>
    <button type="button" className="min-w-0 flex-1 border-0 bg-transparent p-0 text-left focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/30" onClick={() => onOpen(entry)}>
      <span className="block truncate text-xs text-primary" title={entry.path}>{entry.name}</span>
      <span className="flex min-w-0 flex-wrap gap-x-2 text-[10px] text-muted"><span>{fileTypeLabel(entry)}</span>{!entry.isDirectory ? <span>{sizeLabel(entry.size)}</span> : null}<time dateTime={entry.modifiedAt} title={entry.modifiedAt || '时间未知'}>{formatModifiedAt(entry.modifiedAt)}</time></span>
    </button>
    {!entry.isDirectory ? <>
      <IconButton label={`预览 ${entry.name}`} title="预览" onClick={() => onPreview(entry)}><Eye size={14} /></IconButton>
      <IconButton label={`下载 ${entry.name}`} title="下载" onClick={() => onDownload(entry)}><Download size={14} /></IconButton>
    </> : null}
    <IconButton label={`删除 ${entry.name}`} title="删除" variant="danger" disabled={deleting} onClick={() => onDelete(entry)}><Trash2 size={14} /></IconButton>
  </div>
}
