/** Keep the source stem while discarding paths and illegal filename characters. */
export function exportBaseName(path: string | undefined): string {
  const name = (path ?? '').split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') ?? ''
  return name.replace(/[\u0000-\u001f<>:"/\\|?*]+/g, '_').trim() || 'slides'
}

export function downloadSlidesBlob(blob: Blob, filename: string): void {
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  link.href = url
  link.download = filename
  document.body.append(link)
  try { link.click() }
  finally {
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
}
