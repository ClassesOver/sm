import { expect, it } from 'vitest'
import { catalogSchema, detailSchema } from './contracts'
it('区分草稿、已发布与实际生效版本，不把待重启误判为已生效', () => {
  const value = detailSchema.parse({ draft: { version: 2, document: { values: {} }, contentHash: 'draft', updatedAt: 'date' },
    initial: {}, effective: { revision: 1, draftVersion: 2, document: {}, contentHash: 'published', publishedAt: 'date' },
    changes: [], application: { canApply: true, status: 'restart_required', requiresRestart: true, effectiveRevision: null,
      publishedRevision: 1, reason: '重启后生效' } })
  expect(value.application.effectiveRevision).toBeNull()
  expect(value.effective?.revision).toBe(1)
  expect(value.application.requiresRestart).toBe(true)
})
it('未知字段类型拒绝进入配置表单', () => {
  expect(catalogSchema.safeParse({ items: [{ type: 'code' }] }).success).toBe(false)
})
