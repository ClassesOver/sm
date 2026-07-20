import type { WorkspaceEntry } from '../types'

export type WorkspaceSortKey = 'name' | 'modifiedAt' | 'size'
export type WorkspaceSortDirection = 'asc' | 'desc'

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

function compareEntries(
  left: WorkspaceEntry,
  right: WorkspaceEntry,
  key: WorkspaceSortKey,
  direction: WorkspaceSortDirection
): number {
  if (left.isDirectory !== right.isDirectory) return left.isDirectory ? -1 : 1

  let result = 0
  if (key === 'name') {
    result = collator.compare(left.name, right.name)
  } else if (key === 'size') {
    const leftSize = Number.isFinite(left.size) ? left.size : 0
    const rightSize = Number.isFinite(right.size) ? right.size : 0
    result = leftSize - rightSize
  } else {
    const leftTime = new Date(left.modifiedAt).getTime()
    const rightTime = new Date(right.modifiedAt).getTime()
    const leftValid = Number.isFinite(leftTime)
    const rightValid = Number.isFinite(rightTime)
    if (leftValid !== rightValid) return leftValid ? -1 : 1
    if (leftValid && rightValid) result = leftTime - rightTime
  }

  if (result === 0) result = collator.compare(left.name, right.name)
  return direction === 'asc' ? result : -result
}

export function getVisibleWorkspaceEntries(
  entries: WorkspaceEntry[],
  search: string,
  sortKey: WorkspaceSortKey,
  sortDirection: WorkspaceSortDirection
): WorkspaceEntry[] {
  const query = search.trim().toLocaleLowerCase('zh-CN')
  const filtered = query
    ? entries.filter((entry) => entry.name.toLocaleLowerCase('zh-CN').includes(query))
    : entries
  return [...filtered].sort((left, right) => compareEntries(left, right, sortKey, sortDirection))
}

export function workspaceErrorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback
}

export function workspaceEntryContains(entry: WorkspaceEntry, path: string): boolean {
  return entry.path === path || (entry.isDirectory && path.startsWith(`${entry.path}/`))
}
