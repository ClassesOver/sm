import { describe, expect, it } from 'vitest'
import { canPreviewFile, getFilePreviewType } from './filePreviewType'

describe('file preview type', () => {
  it('recognizes names before MIME types and normalizes extensions', () => {
    expect(getFilePreviewType('报告.XLSX?version=1', 'application/octet-stream')).toBe('xlsx')
    expect(getFilePreviewType('合同', 'application/pdf')).toBe('pdf')
    expect(getFilePreviewType('图片', 'image/png')).toBe('png')
    expect(getFilePreviewType('说明', 'text/markdown')).toBe('md')
  })

  it('separates supported previews from download-only formats', () => {
    expect(canPreviewFile('docx')).toBe(true)
    expect(canPreviewFile('PDF')).toBe(true)
    expect(canPreviewFile('bin')).toBe(false)
  })
})
