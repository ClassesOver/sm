import { ExternalLink, FileText } from 'lucide-react'
import type { AttachmentRef, ChatLabels } from '../types'
import { AsidePanel } from './AsidePanel'
import { getFilePreviewType } from './filePreviewType'
import { LazyFileViewer } from './LazyFileViewer'

interface FilePreviewPanelProps {
  attachment: AttachmentRef
  labels: ChatLabels
  onClose: () => void
}

function attachmentUrl(attachment: AttachmentRef): string {
  return `/agui_chat/attachment/${encodeURIComponent(attachment.id)}`
}

export function getAttachmentPreviewType(attachment: AttachmentRef): string {
  return getFilePreviewType(attachment.name, attachment.mimeType)
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
