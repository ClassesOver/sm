import type { FilterResult, RelationSearchResult, ToolCall } from '../types'
import { toolName } from '../runtime/utils'

export type BuiltInToolPresentation =
  | { kind: 'relation_search'; result: RelationSearchResult }
  | { kind: 'record_candidates'; result: FilterResult }
  | { kind: 'default' }

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isRelationSearchResult(value: unknown): value is RelationSearchResult {
  if (!isRecord(value) || value.ok !== true || !Array.isArray(value.candidates)) return false
  return value.operation === 'odoo.search_relation' &&
    typeof value.field === 'string' &&
    (value.fieldLabel === undefined || typeof value.fieldLabel === 'string') &&
    (value.fieldType === 'many2one' || value.fieldType === 'many2many') &&
    typeof value.relation === 'string' &&
    (value.rowToken === undefined || value.rowToken === false || typeof value.rowToken === 'string') &&
    typeof value.query === 'string' &&
    ['set', 'link', 'unlink'].includes(String(value.relationOperation)) &&
    ['none', 'unique_exact', 'ambiguous'].includes(String(value.resolution)) &&
    typeof value.snapshotId === 'string' &&
    typeof value.hostRevision === 'number' &&
    value.candidates.every((candidate) => isRecord(candidate) &&
      typeof candidate.id === 'number' &&
      typeof candidate.displayName === 'string' &&
      typeof candidate.selected === 'boolean')
}

function isFilterResult(value: unknown): value is FilterResult {
  if (!isRecord(value) || value.ok !== true || !Array.isArray(value.candidates)) return false
  return value.operation === 'odoo.apply_filter' &&
    typeof value.label === 'string' &&
    Array.isArray(value.domain) &&
    typeof value.count === 'number' &&
    typeof value.snapshotId === 'string' &&
    typeof value.hostRevision === 'number' &&
    value.candidates.every((candidate) => isRecord(candidate) &&
      typeof candidate.token === 'string' &&
      typeof candidate.displayName === 'string')
}

export function getBuiltInToolPresentation(tool: ToolCall): BuiltInToolPresentation {
  const name = toolName(tool)
  if (name === 'odoo.search_relation' && isRelationSearchResult(tool.result)) {
    return { kind: 'relation_search', result: tool.result }
  }
  if (name === 'odoo.apply_filter' && isFilterResult(tool.result)) {
    return { kind: 'record_candidates', result: tool.result }
  }
  return { kind: 'default' }
}
