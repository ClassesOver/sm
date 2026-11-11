import { z } from 'zod'

const scalar = z.union([z.string(), z.number(), z.boolean(), z.null()])
const period = z.object({ start: z.string(), end: z.string() })
const dimension = z.object({ dimensionId: z.string(), value: scalar })
export const policyDefinitionSchema = z.object({
  id: z.string(), name: z.string(), scenario: z.string(), validFrom: z.string(), validTo: z.string().nullable(),
  metricVersions: z.array(z.object({ metricId: z.string(), revision: z.number().int().nonnegative() })),
  evidenceReleaseId: z.string(), decisionNotes: z.string(),
  filters: z.array(z.object({ fieldRef: z.string(), operator: z.enum(['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'in', 'is_null']), values: z.array(scalar) })),
  joins: z.array(z.object({ leftKeys: z.array(z.string()), rightKeys: z.array(z.string()), cardinality: z.literal('many_to_one'), outputGrain: z.array(z.string()) })),
  readinessPolicy: z.object({ expectedPeriods: z.array(period), expectedGroups: z.array(z.array(dimension)),
    watermarkField: z.string().nullable(), maximumDelaySeconds: z.number().int().nonnegative().nullable(),
    emptyObservation: z.enum(['unknown', 'zero_when_complete']) }),
})
export type PolicyDefinition = z.infer<typeof policyDefinitionSchema>
export const policyDocumentSchema = policyDefinitionSchema.extend({ scopeId: z.string(), revision: z.number().int().positive() })
export const policyDraftSchema = z.object({ version: z.number().int().positive(), document: policyDocumentSchema, contentHash: z.string() })
export const policyPublishedSchema = z.object({ revision: z.number().int().positive(), document: policyDocumentSchema, contentHash: z.string() })
export const policyReadSchema = z.object({ draft: policyDraftSchema.nullable(), published: policyPublishedSchema.nullable() })
export const policyIssuesSchema = z.array(z.object({ code: z.string().optional(), impact: z.string().optional(), message: z.string() }))
export const policyPreviewSchema = z.object({ calculationChanged: z.boolean(), changedFields: z.array(z.string()),
  metricVersionsChanged: z.boolean(), evidenceChanged: z.boolean(), issues: policyIssuesSchema })
export const samePolicy = (a: PolicyDefinition, b: PolicyDefinition) => JSON.stringify(policyDefinitionSchema.parse(a)) === JSON.stringify(policyDefinitionSchema.parse(b))
