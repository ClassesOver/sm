import { ChevronRight, FileText } from 'lucide-react'
import type { AttachmentRef, ChatLabels } from '../types'

interface MessageAttachmentProps {
  attachment: AttachmentRef
  labels: ChatLabels
  onPreview: (attachment: AttachmentRef) => void
}

interface MessageAttachmentsProps {
  attachments?: AttachmentRef[]
  labels: ChatLabels
  onPreview: (attachment: AttachmentRef) => void
}

function attachmentUrl(attachment: AttachmentRef): string {
  return `/agui_chat/attachment/${encodeURIComponent(attachment.id)}`
}

function attachmentMeta(attachment: AttachmentRef): string {
  const type = attachment.mimeType.includes('pdf') ? 'PDF' : attachment.mimeType.split('/').pop()?.toUpperCase() || '文件'
  const size = attachment.size < 1024 * 1024
    ? `${Math.max(1, Math.round(attachment.size / 1024))} KB`
    : `${(attachment.size / (1024 * 1024)).toFixed(2)} MB`
  return `${type} 文档 · ${size}`
}

export function MessageAttachment({ attachment, labels, onPreview }: MessageAttachmentProps) {
  if (attachment.modality === 'image') {
    return <button type="button" className="border-0 bg-transparent p-0" aria-label={`${labels.filePreview}: ${attachment.name}`} onClick={() => onPreview(attachment)}>
      <img className="h-28 w-40 rounded-lg border border-border object-cover" src={attachmentUrl(attachment)} alt={attachment.name} />
    </button>
  }

  return <button type="button" className="flex h-14 w-60 max-w-full items-center gap-2 rounded-lg border border-solid border-border bg-background-panel px-2.5 text-left text-xs text-primary hover:bg-background-secondary" aria-label={`${labels.filePreview}: ${attachment.name}`} onClick={() => onPreview(attachment)}>
    <span className="grid size-7 shrink-0 place-items-center rounded bg-background-secondary"><FileText className="size-4" /></span>
    <span className="min-w-0 flex-1"><span className="block truncate">{attachment.name}</span><span className="mt-0.5 block truncate text-[11px] text-muted">{attachmentMeta(attachment)}</span></span>
    <ChevronRight className="size-4 shrink-0 text-muted" />
  </button>
}

export function MessageAttachments({ attachments, labels, onPreview }: MessageAttachmentsProps) {
  if (!attachments?.length) return null

  return <div className="mb-2 flex flex-wrap justify-end gap-2">{attachments.map((attachment) => (
    <MessageAttachment key={attachment.id} attachment={attachment} labels={labels} onPreview={onPreview} />
  ))}</div>
}
