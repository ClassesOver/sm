import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { RelationSearchResult } from '../types'
import {
  isCandidateSnapshotStale,
  isRelationCandidateCompatible,
  useRelationCandidateSelection
} from './useRelationCandidateSelection'

afterEach(cleanup)

function relationResult(overrides: Partial<RelationSearchResult> = {}): RelationSearchResult {
  return {
    ok: true,
    operation: 'odoo.search_relation',
    field: 'category_id',
    fieldType: 'many2many',
    relation: 'res.partner.category',
    query: '重点',
    relationOperation: 'link',
    resolution: 'ambiguous',
    candidates: [{ id: 7, displayName: '重点客户', selected: false }],
    snapshotId: 'snapshot-1',
    hostRevision: 1,
    ...overrides
  }
}

describe('关系候选选择', () => {
  it('统一判断快照和关系操作兼容性', () => {
    const candidate = { id: 7, displayName: '重点客户', selected: false }
    expect(isRelationCandidateCompatible('link', candidate)).toBe(true)
    expect(isRelationCandidateCompatible('unlink', candidate)).toBe(false)
    expect(isRelationCandidateCompatible('set', candidate)).toBe(true)
    expect(isCandidateSnapshotStale(relationResult(), {
      snapshotId: 'snapshot-1',
      hostRevision: 2
    })).toBe(true)
  })

  it('候选范围变化后不保留旧选择', () => {
    const first = relationResult()
    const { result, rerender } = renderHook(
      ({ value }) => useRelationCandidateSelection(value),
      { initialProps: { value: first } }
    )

    act(() => result.current.toggleCandidate(first.candidates[0]))
    expect(result.current.selectedIds).toEqual([7])
    expect(result.current.selectedCandidates).toEqual(first.candidates)

    const next = relationResult({
      candidates: [{ id: 8, displayName: '战略客户', selected: false }]
    })
    rerender({ value: next })
    expect(result.current.selectedIds).toEqual([])
    expect(result.current.selectedCandidates).toEqual([])

    rerender({ value: first })
    expect(result.current.selectedIds).toEqual([])
    expect(result.current.selectedCandidates).toEqual([])

    act(() => result.current.toggleCandidate(first.candidates[0]))
    expect(result.current.selectedIds).toEqual([7])
  })

  it('忽略与 link 操作不兼容的已关联候选', () => {
    const value = relationResult({
      candidates: [{ id: 7, displayName: '重点客户', selected: true }]
    })
    const { result } = renderHook(() => useRelationCandidateSelection(value))

    act(() => result.current.toggleCandidate(value.candidates[0]))
    expect(result.current.selectedIds).toEqual([])
  })
})
