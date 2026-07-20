import { X } from 'lucide-react'
import type { ChatLabels } from '../types'
import { cn } from '../lib'
import { Button } from './Button'
import { IconButton } from './IconButton'
import type { UploadItem } from './useComposerAttachments'

export type { UploadItem } from './useComposerAttachments'

const MB = 1024 * 1024

interface AttachmentItemProps {
  item: UploadItem
  removeLabel: string
  onRemove: (item: UploadItem) => void
}

interface AttachmentQueueProps {
  items: UploadItem[]
  labels: ChatLabels
  onClear: () => void
  onRemove: (item: UploadItem) => void
}

function formatSize(size: number): string {
  return size < MB ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / MB).toFixed(1)} MB`
}

function fileBadge(file: File): string {
  const extension = file.name.split('.').pop()?.toUpperCase()
  return extension && extension.length <= 4 ? extension : '文件'
}

function fileKind(file: File): string {
  if (file.type === 'application/pdf') return 'PDF 文档'
  if (file.type.includes('spreadsheet') || file.type.includes('excel') || file.type === 'text/csv') return 'Excel 表格'
  if (file.type.includes('word')) return 'Word 文档'
  if (file.type.startsWith('image/')) return '图片'
  if (file.type.startsWith('text/')) return '文本文件'
  return '文档'
}

export function AttachmentItem({ item, removeLabel, onRemove }: AttachmentItemProps) {
  return <div className="relative flex h-14 w-52 min-w-0 items-center gap-2 rounded-md border border-border bg-background-panel p-2 pr-7 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
    {item.previewUrl ? (
      <img className="size-9 shrink-0 rounded object-cover" src={item.previewUrl} alt="" />
    ) : (
      <span className={cn(
        'grid size-9 shrink-0 place-items-center rounded-md border border-border bg-background-secondary text-[9px] font-semibold text-primary',
        (item.file.type.includes('spreadsheet') || item.file.type === 'text/csv') && 'text-positive'
      )}>{fileBadge(item.file)}</span>
    )}
    <div className="min-w-0 flex-1">
      <div className="truncate text-xs font-medium text-primary" title={item.file.name}>{item.file.name}</div>
      <div className={cn('mt-0.5 truncate text-[10px] text-muted', item.error && 'text-destructive')}>
        {item.error || (item.status === 'uploading' ? `上传中 ${item.progress}%` : `${fileKind(item.file)} · ${formatSize(item.file.size)}`)}
      </div>
      {item.status === 'uploading' ? (
        <div className="mt-1 h-1 overflow-hidden rounded bg-border">
          <div className="h-full bg-primary" style={{ width: `${item.progress}%` }} />
        </div>
      ) : null}
    </div>
    <IconButton label={`${removeLabel} ${item.file.name}`} size="xs" className="absolute -right-1.5 -top-1.5 size-5 rounded-full border-background-panel bg-muted p-0 text-background-panel shadow-sm hover:bg-primary hover:text-background-panel" onClick={() => onRemove(item)}>
      <X className="size-3" />
    </IconButton>
  </div>
}

export function AttachmentQueue({ items, labels, onClear, onRemove }: AttachmentQueueProps) {
  if (!items.length) return null

  return <div className="mb-3" aria-label={labels.attachments}>
    <div className="mb-2 flex h-5 items-center justify-between gap-3 text-xs text-muted">
      <span>{labels.uploadedAttachments.replace('{count}', String(items.length))}</span>
      <Button
        variant="ghost"
        size="sm"
        className="h-6 rounded border-0 px-1 text-xs text-secondary"
        aria-label={labels.clearAttachments}
        onClick={onClear}
      >
        <X className="size-3" />{labels.clearAttachments}
      </Button>
    </div>
    <div className="flex flex-wrap gap-2">
      {items.map((item) => <AttachmentItem
        key={item.localId}
        item={item}
        removeLabel={labels.removeAttachment}
        onRemove={onRemove}
      />)}
    </div>
  </div>
}
