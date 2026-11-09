/** Read/export adaptation of pinned GenOffice AttachmentsPanel/App.
 * Source and deliberate differences: genoffice-pdf-attachments-source.json.
 */
export interface PdfAttachmentMetadata { filename: string; description: string; rawFilename?: string; content?: Uint8Array | null }
export interface PdfAttachmentDocument { getAttachments(): Promise<Map<string, PdfAttachmentMetadata> | null>; getAttachmentContent(id: string): Promise<Uint8Array | null> }
export interface PdfAttachmentRow { id: string; filename: string; description: string; metadata: PdfAttachmentMetadata }

// Unchanged from upstream AttachmentsPanel.tsx (Apache-2.0).
export function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}
export function attachmentDownloadName(name: string): string {
  return name.split(/[\\/]/).at(-1)?.replace(/[\u0000-\u001f\u007f]/g, '').trim() || 'attachment'
}
export class PdfAttachmentCache {
  private documents = new WeakMap<PdfAttachmentDocument, { rows?: Promise<PdfAttachmentRow[]>; contents: Map<string, Promise<Uint8Array>> }>()
  private entry(document: PdfAttachmentDocument) {
    let entry = this.documents.get(document)
    if (!entry) { entry = { contents: new Map() }; this.documents.set(document, entry) }
    return entry
  }
  rows(document: PdfAttachmentDocument): Promise<PdfAttachmentRow[]> {
    const entry = this.entry(document)
    if (!entry.rows) {
      const result = document.getAttachments().then(all => {
        if (all === null) return []
        if (!(all instanceof Map)) throw new Error('附件目录无法读取')
        return [...all].map(([id, metadata]) => {
          if (typeof id !== 'string' || !metadata || typeof metadata.filename !== 'string') throw new Error('附件目录无法读取')
          return { id, filename: metadata.filename, description: typeof metadata.description === 'string' ? metadata.description : '', metadata }
        })
      })
      entry.rows = result
      void result.catch(() => { if (entry.rows === result) entry.rows = undefined })
    }
    return entry.rows
  }
  content(document: PdfAttachmentDocument, row: PdfAttachmentRow): Promise<Uint8Array> {
    const entry = this.entry(document)
    let result = entry.contents.get(row.id)
    if (!result) {
      result = Promise.resolve().then(async () => {
        const bytes = row.metadata.content ?? await document.getAttachmentContent(row.id)
        if (!(bytes instanceof Uint8Array)) throw new Error('附件内容无法读取')
        return bytes
      })
      entry.contents.set(row.id, result)
      const pending = result
      void result.catch(() => { if (entry.contents.get(row.id) === pending) entry.contents.delete(row.id) })
    }
    return result
  }
  clear() { this.documents = new WeakMap() }
}
