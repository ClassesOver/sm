import { ExternalLink, FileText } from 'lucide-react'
import type { AttachmentRef, ChatLabels } from '../types'
import { AsidePanel } from './AsidePanel'
import { LazyFileViewer } from './LazyFileViewer'

interface FilePreviewPanelProps {
  attachment: AttachmentRef
  labels: ChatLabels
  onClose: () => void
}

function attachmentUrl(attachment: AttachmentRef): string {
  return `/agui_chat/attachment/${encodeURIComponent(attachment.id)}`
}

function extensionFromName(name: string): string {
  const cleanName = name.split(/[?#]/)[0]
  const dotIndex = cleanName.lastIndexOf('.')
  return dotIndex >= 0 && dotIndex < cleanName.length - 1
    ? cleanName.slice(dotIndex + 1).toLowerCase()
    : ''
}

function extensionFromMime(mimeType: string): string {
  if (mimeType.includes('pdf')) return 'pdf'
  if (mimeType.includes('wordprocessingml')) return 'docx'
  if (mimeType.includes('msword')) return 'doc'
  if (mimeType.includes('spreadsheetml')) return 'xlsx'
  if (mimeType.includes('vnd.ms-excel')) return 'xls'
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return 'pptx'
  if (mimeType.includes('ofd')) return 'ofd'
  if (mimeType.startsWith('image/') || mimeType.startsWith('audio/') || mimeType.startsWith('video/')) {
    return mimeType.split('/')[1] || ''
  }
  if (mimeType.includes('json')) return 'json'
  if (mimeType.startsWith('text/')) return mimeType.includes('markdown') ? 'md' : 'txt'
  return ''
}

export function getAttachmentPreviewType(attachment: AttachmentRef): string {
  return extensionFromName(attachment.name) || extensionFromMime(attachment.mimeType) || attachment.mimeType
}

export function FilePreviewPanel({ attachment, labels, onClose }: FilePreviewPanelProps) {
  const url = attachmentUrl(attachment)

  return <AsidePanel
    className="agui-file-preview"
    ariaLabel={labels.filePreview}
    eyebrow={labels.filePreview}
    title={attachment.name}
    icon={<FileText size={13} strokeWidth={1.8} />}
    closeLabel={labels.closeFilePreview}
    resizeLabel="调整文件预览宽度"
    onClose={onClose}
    actions={<a href={url} target="_blank" rel="noopener noreferrer" aria-label={labels.openFile} title={labels.openFile}><ExternalLink size={16} /></a>}
  >
    <LazyFileViewer
      key={attachment.id}
      className="agui-file-viewer"
      errorLabel={labels.previewUnavailable}
      url={url}
      filename={attachment.name}
      name={attachment.name}
      type={getAttachmentPreviewType(attachment)}
      options={{ theme: 'light', styleIsolation: 'shadow' }}
    />
  </AsidePanel>
}
