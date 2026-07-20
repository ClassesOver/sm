import { useCallback, useEffect, useState } from 'react'
import type { WorkspaceEntry, WorkspaceReference } from '../types'

export const MAX_WORKSPACE_REFERENCES = 5

export function useWorkspaceReferences(threadId: string) {
  const [references, setReferences] = useState<WorkspaceReference[]>([])

  useEffect(() => setReferences([]), [threadId])

  const clearReferences = useCallback(() => setReferences([]), [])

  const removeReference = useCallback((id: string) => {
    setReferences((current) => current.filter((item) => item.id !== id))
  }, [])

  const toggleReference = useCallback((entry: WorkspaceEntry) => {
    setReferences((current) => {
      const selected = current.some((item) => item.path === entry.path)
      if (selected) return current.filter((item) => item.path !== entry.path)
      if (current.length >= MAX_WORKSPACE_REFERENCES) return current
      return [...current, {
        id: `workspace:${entry.path}`,
        path: entry.path,
        name: entry.name,
        isDirectory: entry.isDirectory
      }]
    })
  }, [])

  const removeDeleted = useCallback((entry: WorkspaceEntry) => {
    setReferences((current) => current.filter((item) =>
      item.path !== entry.path && !(entry.isDirectory && item.path.startsWith(`${entry.path}/`))
    ))
  }, [])

  return {
    references,
    clearReferences,
    removeReference,
    toggleReference,
    removeDeleted
  }
}
