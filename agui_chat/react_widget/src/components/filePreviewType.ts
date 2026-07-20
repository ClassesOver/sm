const PREVIEWABLE_TYPES = new Set([
  'pdf', 'ofd', 'doc', 'docx', 'docm', 'dot', 'dotx', 'dotm', 'rtf', 'odt',
  'xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'xltm', 'csv', 'ods', 'fods', 'numbers',
  'ppt', 'pptx', 'pptm', 'potx', 'potm', 'ppsx', 'ppsm', 'odp',
  'gif', 'jpg', 'jpeg', 'bmp', 'tiff', 'tif', 'png', 'svg', 'svg+xml', 'webp', 'avif', 'ico', 'heic', 'heif', 'jxl',
  'txt', 'json', 'jsonl', 'jsonc', 'json5', 'js', 'mjs', 'cjs', 'css', 'java', 'py', 'html', 'htm', 'jsx', 'ts',
  'tsx', 'xml', 'log', 'vue', 'yaml', 'yml', 'ini', 'sh', 'bash', 'sql', 'go', 'rs', 'php', 'c', 'cpp', 'cc',
  'h', 'hpp', 'cs', 'diff', 'patch', 'toml', 'proto', 'hcl', 'tex', 'gv', 'http', 'rb', 'swift', 'kt', 'md', 'markdown'
])

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

export function getFilePreviewType(name: string, mimeType: string | false | undefined): string {
  const normalizedMime = typeof mimeType === 'string' ? mimeType.toLowerCase() : ''
  return extensionFromName(name) || extensionFromMime(normalizedMime) || normalizedMime
}

export function canPreviewFile(type: string): boolean {
  return PREVIEWABLE_TYPES.has(type.toLowerCase())
}
