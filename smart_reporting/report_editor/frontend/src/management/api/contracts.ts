import { z } from 'zod'
export const sessionSchema = z.object({
  username: z.string(),
  csrfToken: z.string(),
})
export const scopeSchema = z.object({
  id: z.string(),
  name: z.string(),
  database: z.string(),
  companyId: z.string(),
})
export const draftSchema = z.object({
  source_id: z.string(),
  version: z.number().int(),
  name: z.string(),
  source_type: z.string(),
  database: z.string(),
  profile_version_id: z.string().nullable(),
  metadata_version_id: z.string().nullable(),
  content_hash: z.string(),
})
export const publishedSchema = z.object({
  sourceId: z.string(),
  revision: z.number().int(),
  contentHash: z.string(),
  publishedAt: z.string(),
  name: z.string(),
  type: z.string(),
  database: z.string(),
  reportingProfileVersionId: z.string().nullable(),
  metadataVersionId: z.string().nullable(),
})
export const sourceSchema = draftSchema.extend({
  enabled: z.boolean(),
  publishedRevision: z.number().nullable(),
  publishedTableCount: z.number().default(0),
  hasUnpublishedChanges: z.boolean(),
})
export const detailSchema = z.object({
  draft: draftSchema,
  published: publishedSchema.nullable(),
  enabled: z.boolean(),
  hasUnpublishedChanges: z.boolean(),
})
export const optionSchema = z.object({
  ref: z.string(),
  revision: z.number(),
  publishedAt: z.string().nullable(),
  syncedAt: z.string().optional(),
  profileId: z.string().optional(),
})
export const checkSchema = z.object({
  tableAccessChanges: z
    .object({
      added: z.array(z.string()),
      removed: z.array(z.string()),
      beforeCount: z.number(),
      afterCount: z.number(),
    })
    .optional(),
  expectedVersion: z.number(),
  currentPublishedRevision: z.number().nullable(),
  changedFields: z.array(
    z.object({ field: z.string(), before: z.unknown(), after: z.unknown() }),
  ),
  connectionChanged: z.boolean(),
  hasUnpublishedChanges: z.boolean(),
  canPublish: z.boolean(),
  warnings: z.array(z.string()).default([]),
  issues: z.array(
    z.object({
      code: z.string(),
      message: z.string(),
      field: z.string().optional(),
    }),
  ),
})
export const pageSchema = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), nextCursor: z.string().nullable() })
export type Scope = z.infer<typeof scopeSchema>
export type Draft = z.infer<typeof draftSchema>
export type Source = z.infer<typeof sourceSchema>
export type Detail = z.infer<typeof detailSchema>
export type Session = z.infer<typeof sessionSchema>
export type ReleaseCheck = z.infer<typeof checkSchema>
export type VersionOption = z.infer<typeof optionSchema>

export const tableIdentitySchema = z.object({
  database: z.string(),
  name: z.string(),
})
export const tableAccessSchema = z.object({
  draftVersion: z.number(),
  draftTables: z.array(tableIdentitySchema),
  publishedTables: z.array(tableIdentitySchema),
  needsDiscovery: z.boolean(),
  discoveryId: z.string().nullable(),
  discoveredAt: z.string().nullable(),
  warnings: z.array(z.string()),
})
export const discoverySchema = z.object({
  discoveryId: z.string(),
  discoveredAt: z.string(),
  tableCount: z.number(),
  draftVersion: z.number(),
  warnings: z.array(z.string()),
})
export const discoveredTableSchema = tableIdentitySchema.extend({
  type: z.enum(['table', 'view']),
  description: z.string(),
  selected: z.boolean(),
  published: z.boolean(),
})
export const discoveredTablesSchema = z.object({
  items: z.array(discoveredTableSchema),
  total: z.number(),
  nextOffset: z.number().nullable(),
  selectedItems: z.array(discoveredTableSchema).default([]),
  missingTables: z.array(tableIdentitySchema),
})
export const tableColumnsSchema = tableIdentitySchema.extend({
  columns: z.array(
    z.object({
      name: z.string(),
      dataType: z.string(),
      nullable: z.boolean(),
      description: z.string(),
    }),
  ),
})
export const savedAccessSchema = z.object({
  draftVersion: z.number(),
  metadataVersionId: z.string(),
  warnings: z.array(z.string()),
})
export type TableIdentity = z.infer<typeof tableIdentitySchema>

export type DiscoveredTable = z.infer<typeof discoveredTableSchema>
