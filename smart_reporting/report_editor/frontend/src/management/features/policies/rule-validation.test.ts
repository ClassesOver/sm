import { expect, it } from 'vitest'
import { validatePolicyRules } from './rule-validation'
import type { PolicyDefinition } from './editor-contracts'
const valid: Pick<PolicyDefinition, 'filters' | 'joins' | 'readinessPolicy'> = { filters: [], joins: [], readinessPolicy: { expectedPeriods: [], expectedGroups: [], watermarkField: null, maximumDelaySeconds: null, emptyObservation: 'unknown' } }
it('accepts unspecified readiness without inventing completeness', () => { expect(validatePolicyRules(valid)).toBe('') })
it('rejects invalid filter fields and operator arity', () => {
 expect(validatePolicyRules({ ...valid, filters: [{ fieldRef: 'budget.*', operator: 'eq', values: ['A'] }] })).toContain('筛选')
 expect(validatePolicyRules({ ...valid, filters: [{ fieldRef: 'source.db.table.field', operator: 'is_null', values: ['A'] }] })).toContain('筛选')
})
it('rejects unpaired joins and missing output grain', () => {
 expect(validatePolicyRules({ ...valid, joins: [{ leftKeys: ['source.db.table.field'], rightKeys: [], cardinality: 'many_to_one', outputGrain: ['project'] }] })).toContain('关联')
})
it('rejects invalid or overlapping expected periods without silently normalizing dates', () => {
 for (const periods of [[{ start: '2026-02-30', end: '2026-03-05' }], [{ start: '2026-01-01', end: '2026-03-01' }, { start: '2026-02-01', end: '2026-04-01' }]])
  expect(validatePolicyRules({ ...valid, readinessPolicy: { ...valid.readinessPolicy, expectedPeriods: periods } })).toContain('期间')
})
it('requires a watermark for a delay threshold and distinct typed expected groups', () => {
 expect(validatePolicyRules({ ...valid, readinessPolicy: { ...valid.readinessPolicy, maximumDelaySeconds: 1 } })).toContain('水位')
 const groups = [[{ dimensionId: 'project', value: 'A' }], [{ dimensionId: 'project', value: 'A' }]]
 expect(validatePolicyRules({ ...valid, readinessPolicy: { ...valid.readinessPolicy, expectedGroups: groups } })).toContain('分组')
 expect(validatePolicyRules({ ...valid, readinessPolicy: { ...valid.readinessPolicy, expectedGroups: [[{ dimensionId: 'project', value: '1' }], [{ dimensionId: 'project', value: 1 }]] } })).toBe('')
})
