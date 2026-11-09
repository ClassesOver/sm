import { expect, it } from 'vitest'
import { PdfAttachmentCache, attachmentDownloadName, humanBytes } from './pdf-attachments'
const row = (filename = 'same.txt') => ({ filename, description: '' })
it('keeps IDs distinct despite duplicate names, shares inflight reads and caches empty bytes', async () => {
  let lists = 0, reads = 0
  const document = { getAttachments: async () => { lists++; return new Map([['first', row()], ['second', row()]]) }, getAttachmentContent: async (id: string) => { reads++; return id === 'first' ? new Uint8Array() : new Uint8Array([0, 255, 1]) } }
  const cache = new PdfAttachmentCache(), pending = cache.rows(document)
  expect(cache.rows(document)).toBe(pending)
  const rows = await pending; expect(rows.map(r => r.id)).toEqual(['first', 'second']); expect(lists).toBe(1)
  const first = cache.content(document, rows[0]); expect(cache.content(document, rows[0])).toBe(first)
  expect(await first).toHaveLength(0); expect(await cache.content(document, rows[1])).toEqual(new Uint8Array([0, 255, 1])); expect(reads).toBe(2)
})
it('evicts failed metadata/content and separates actual preview document instances', async () => {
  let failList = true, failContent = true, lists = 0, reads = 0
  const document = { getAttachments: async () => { lists++; if (failList) throw Error('list'); return new Map([['x', row()]]) }, getAttachmentContent: async () => { reads++; if (failContent) throw Error('content'); return new Uint8Array([1]) } }
  const cache = new PdfAttachmentCache()
  await expect(cache.rows(document)).rejects.toThrow('list'); failList = false
  const [r] = await cache.rows(document); await expect(cache.content(document, r)).rejects.toThrow('content'); failContent = false
  await cache.content(document, r); await cache.content(document, r); expect(reads).toBe(2)
  await cache.rows({ ...document }); expect(lists).toBe(3)
  cache.clear(); await cache.rows(document); expect(lists).toBe(4)
})
it('uses inline content and rejects malformed/absent data instead of successful empty downloads', async () => {
  let payload: unknown = {}, reads = 0
  const document = { getAttachments: async () => payload as Map<string, ReturnType<typeof row>>, getAttachmentContent: async () => { reads++; return null } }, cache = new PdfAttachmentCache()
  await expect(cache.rows(document)).rejects.toThrow(/目录/)
  payload = new Map([['bad', { filename: 3 }]]); await expect(cache.rows(document)).rejects.toThrow(/目录/)
  payload = null; expect(await cache.rows(document)).toEqual([])
  const r = { id: 'inline', filename: 'x', description: '', metadata: { ...row(), content: new Uint8Array([9]) } }
  expect(await cache.content(document, r)).toEqual(new Uint8Array([9])); expect(reads).toBe(0)
  await expect(cache.content(document, { ...r, id: 'missing', metadata: row() })).rejects.toThrow(/内容/)
})
it('retains source byte formatting and uses basename-only download names', () => {
  expect([0, 1023, 1024, 1048576].map(humanBytes)).toEqual(['0 B', '1023 B', '1.0 KB', '1.0 MB'])
  expect(attachmentDownloadName('dir\\sub/file\u0000.txt')).toBe('file.txt')
  expect(attachmentDownloadName('/')).toBe('attachment')
  expect(attachmentDownloadName('报告.txt')).toBe('报告.txt')
})
