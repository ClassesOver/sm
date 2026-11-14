import { z } from 'zod'
const document = z.record(z.string(), z.unknown())
export const versionSchema = z.object({ revision: z.number().int(), draftVersion: z.number().int(), document,
  contentHash: z.string(), publishedAt: z.string(), approvalId: z.string().uuid().optional() })
export const detailSchema = z.object({ draft: z.object({ version: z.number().int(), document, contentHash: z.string(), updatedAt: z.string() }),
  initial: document, effective: versionSchema.nullable(), changes: z.array(z.object({ path: z.string(), before: z.unknown(), after: z.unknown() })),
  application: z.object({ canApply: z.boolean(), reason: z.string(), status: z.string().optional(), requiresRestart: z.boolean().optional(),
    effectiveRevision: z.number().nullable().optional(), publishedRevision: z.number().nullable().optional(),
    issue: z.object({ code: z.string(), message: z.string() }).nullable().optional() }) })
export type ConfigurationDetail = z.infer<typeof detailSchema>
export const catalogSchema = z.object({ items: z.array(z.object({ key: z.string(), label: z.string(), category: z.string(),
  type: z.enum(['text', 'integer', 'number', 'boolean', 'list']), unit: z.string().nullable(),
  minimum: z.number().nullable(), maximum: z.number().nullable(), choices: z.array(z.string()), dependencies: z.array(z.string()),
  owner: z.string(), activation: z.string(), sensitive: z.boolean(), redacted: z.boolean(), configured: z.boolean(),
  value: z.unknown(), source: z.string(), editable: z.boolean() })) })
export type ConfigurationItem = z.infer<typeof catalogSchema>['items'][number]
export const savedSchema = z.object({ version: z.number().int(), contentHash: z.string() })
export const historySchema = z.object({ items: z.array(versionSchema.omit({ document: true })), nextCursor: z.number().nullable() })
