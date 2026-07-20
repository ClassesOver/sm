import { describe, expect, it } from 'vitest'
import {
  ACCEPTED_ATTACHMENT_SELECTOR,
  getAttachmentModality,
  getAttachmentPolicy,
  validateAttachmentFiles
} from './attachmentPolicy'

const MB = 1024 * 1024

describe('附件规则模型', () => {
  it('归一化启用状态和默认限制', () => {
    expect(getAttachmentPolicy()).toEqual({
      enabled: true,
      maxFileSize: 10 * MB,
      maxFiles: 5,
      maxTotalSize: 25 * MB
    })
    expect(getAttachmentPolicy(false).enabled).toBe(false)
    expect(getAttachmentPolicy({ enabled: false, maxFiles: 2 })).toMatchObject({
      enabled: false,
      maxFiles: 2
    })
    expect(ACCEPTED_ATTACHMENT_SELECTOR).toContain('image/png')
    expect(ACCEPTED_ATTACHMENT_SELECTOR).toContain('.xlsx')
  })

  it('按 MIME 类型或报表扩展名识别附件模态', () => {
    expect(getAttachmentModality(new File(['image'], 'preview.bin', { type: 'image/png' }))).toBe('image')
    expect(getAttachmentModality(new File(['report'], 'report.JSONL'))).toBe('document')
    expect(getAttachmentModality(new File(['binary'], 'archive.zip', { type: 'application/zip' }))).toBeUndefined()
  })

  it('按既有优先级校验类型、单文件大小、数量和总大小', () => {
    const unsupported = new File(['x'], 'archive.zip', { type: 'application/zip' })
    const oversized = new File(['12345'], 'large.txt', { type: 'text/plain' })
    const current = new File(['1234'], 'current.txt', { type: 'text/plain' })
    const next = new File(['12'], 'next.txt', { type: 'text/plain' })

    expect(validateAttachmentFiles([unsupported], [], getAttachmentPolicy())[0].error).toBe('不支持的文件类型')
    expect(validateAttachmentFiles([oversized], [], getAttachmentPolicy({ maxFileSize: 4 }))[0].error).toBe('文件超过 1 KB')
    expect(validateAttachmentFiles([next], [current], getAttachmentPolicy({ maxFiles: 1 }))[0].error).toBe('最多添加 1 个文件')
    expect(validateAttachmentFiles([next], [current], getAttachmentPolicy({ maxTotalSize: 5 }))[0].error).toBe('附件总大小超过 1 KB')
  })

  it('批量校验时让前面的错误项继续占用队列配额', () => {
    const unsupported = new File(['x'], 'archive.zip', { type: 'application/zip' })
    const valid = new File(['ok'], 'report.txt', { type: 'text/plain' })
    const result = validateAttachmentFiles(
      [unsupported, valid],
      [],
      getAttachmentPolicy({ maxFiles: 1 })
    )

    expect(result.map((item) => item.error)).toEqual(['不支持的文件类型', '最多添加 1 个文件'])
  })
})
