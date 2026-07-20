import { useCallback, useEffect, useMemo, useState } from 'react'
import type { OdooHostSnapshot, RelationCandidate, RelationSearchResult } from '../types'

interface CandidateSnapshot {
  snapshotId: string
  hostRevision: number
}

interface RelationSelectionState {
  scope: string
  selectedIds: number[]
}

const EMPTY_SELECTED_IDS: readonly number[] = []

export function isCandidateSnapshotStale(
  result: CandidateSnapshot,
  hostState: Pick<OdooHostSnapshot, 'snapshotId' | 'hostRevision'>
): boolean {
  return result.snapshotId !== hostState.snapshotId || result.hostRevision !== hostState.hostRevision
}

export function isRelationCandidateCompatible(
  operation: RelationSearchResult['relationOperation'],
  candidate: RelationCandidate
): boolean {
  if (operation === 'link') return !candidate.selected
  if (operation === 'unlink') return candidate.selected
  return true
}

export function getRelationSelectionScope(result: RelationSearchResult): string {
  const candidates = result.candidates
    .map((candidate) => [candidate.id, candidate.selected] as const)
    .sort(([left], [right]) => left - right)
  return JSON.stringify([
    result.snapshotId,
    result.hostRevision,
    result.field,
    result.fieldType,
    result.relation,
    result.rowToken || '',
    result.query,
    result.relationOperation,
    candidates
  ])
}

export function toggleRelationCandidateId(selectedIds: readonly number[], candidateId: number): number[] {
  return selectedIds.includes(candidateId)
    ? selectedIds.filter((id) => id !== candidateId)
    : [...selectedIds, candidateId]
}

export function useRelationCandidateSelection(result: RelationSearchResult) {
  const scope = getRelationSelectionScope(result)
  const [selection, setSelection] = useState<RelationSelectionState>(() => ({
    scope,
    selectedIds: []
  }))
  const selectedIds = selection.scope === scope ? selection.selectedIds : EMPTY_SELECTED_IDS

  useEffect(() => {
    setSelection((current) => current.scope === scope
      ? current
      : { scope, selectedIds: [] })
  }, [scope])

  const isCompatible = useCallback((candidate: RelationCandidate) => {
    return isRelationCandidateCompatible(result.relationOperation, candidate)
  }, [result.relationOperation])
  const selectedCandidates = useMemo(() => {
    const ids = new Set(selectedIds)
    return result.candidates.filter((candidate) => ids.has(candidate.id) && isCompatible(candidate))
  }, [isCompatible, result.candidates, selectedIds])

  const toggleCandidate = useCallback((candidate: RelationCandidate) => {
    if (!isRelationCandidateCompatible(result.relationOperation, candidate)) return
    setSelection((current) => ({
      scope,
      selectedIds: toggleRelationCandidateId(
        current.scope === scope ? current.selectedIds : EMPTY_SELECTED_IDS,
        candidate.id
      )
    }))
  }, [result.relationOperation, scope])

  return { selectedIds, selectedCandidates, isCompatible, toggleCandidate }
}
