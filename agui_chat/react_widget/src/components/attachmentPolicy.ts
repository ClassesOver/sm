import type { AttachmentModality, AttachmentOptions } from '../types'

const ACCEPTED_TYPES: Record<string, AttachmentModality> = {
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/webp': 'image',
  'application/pdf': 'document',
  'text/plain': 'document',
  'text/csv': 'document',
  'application/csv': 'document',
  'application/json': 'document',
  'application/jsonl': 'document',
  'application/x-ndjson': 'document',
  'application/vnd.ms-excel': 'document',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'document'
}

const REPORT_EXTENSIONS = new Set(['csv', 'xlsx', 'json', 'jsonl'])
const MB = 1024 * 1024

export const ACCEPTED_ATTACHMENT_SELECTOR = [
  ...Object.keys(ACCEPTED_TYPES),
  ...[...REPORT_EXTENSIONS].map((value) => `.${value}`)
].join(',')

export interface AttachmentPolicy {
  enabled: boolean
  maxFileSize: number
  maxFiles: number
  maxTotalSize: number
}

export interface AttachmentValidation {
  file: File
  modality?: AttachmentModality
  error?: string
}

function formatSize(size: number): string {
  return size < MB ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / MB).toFixed(1)} MB`
}

export function getAttachmentPolicy(attachments?: boolean | AttachmentOptions): AttachmentPolicy {
  const config = typeof attachments === 'object' ? attachments : {}
  return {
    enabled: attachments !== false && config.enabled !== false,
    maxFileSize: config.maxFileSize || 10 * MB,
    maxFiles: config.maxFiles || 5,
    maxTotalSize: config.maxTotalSize || 25 * MB
  }
}

export function getAttachmentModality(file: Pick<File, 'name' | 'type'>): AttachmentModality | undefined {
  const extension = file.name.split('.').pop()?.toLocaleLowerCase() || ''
  return ACCEPTED_TYPES[file.type] || (REPORT_EXTENSIONS.has(extension) ? 'document' : undefined)
}

export function validateAttachmentFiles(
  files: File[],
  currentFiles: File[],
  policy: AttachmentPolicy
): AttachmentValidation[] {
  let count = currentFiles.length
  let totalSize = currentFiles.reduce((sum, file) => sum + file.size, 0)

  return files.map((file) => {
    let error = ''
    const modality = getAttachmentModality(file)
    if (!modality) error = '不支持的文件类型'
    else if (file.size > policy.maxFileSize) error = `文件超过 ${formatSize(policy.maxFileSize)}`
    else if (count >= policy.maxFiles) error = `最多添加 ${policy.maxFiles} 个文件`
    else if (totalSize + file.size > policy.maxTotalSize) error = `附件总大小超过 ${formatSize(policy.maxTotalSize)}`
    count += 1
    totalSize += file.size
    return { file, modality, error: error || undefined }
  })
}
