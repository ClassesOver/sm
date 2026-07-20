import type { ReferenceGroup } from '../types'
import { normalizeReferenceGroups } from '../runtime/utils'

interface MessageReferencesProps {
  references: ReferenceGroup[]
}

export function MessageReferences({ references }: MessageReferencesProps) {
  const groups = normalizeReferenceGroups(references)
  if (!groups.length) return null

  return <div className="flex flex-col gap-3">{groups.map((group, groupIndex) => (
    <div key={`${group.query || 'references'}-${groupIndex}`} className="flex flex-wrap gap-2">
      {group.references.map((reference, index) => {
        const body = <div className="h-20 w-48 overflow-hidden rounded-lg border border-border bg-accent p-3 hover:bg-background-secondary">
          <div className="truncate text-sm font-medium text-primary">{reference.name}</div>
          {reference.content ? <div className="mt-2 line-clamp-2 text-xs leading-4 text-muted">{reference.content}</div> : null}
        </div>
        return reference.url ? <a key={`${reference.name}-${index}`} href={reference.url} target="_blank" rel="noopener noreferrer">{body}</a> : <div key={`${reference.name}-${index}`}>{body}</div>
      })}
    </div>
  ))}</div>
}
