import { ArrowDown, ArrowUp, Search, X } from 'lucide-react'
import { IconButton } from './IconButton'
import type { WorkspaceSortDirection, WorkspaceSortKey } from './workspaceEntryModel'

export type { WorkspaceSortDirection, WorkspaceSortKey } from './workspaceEntryModel'

interface WorkspaceToolbarProps {
  search: string
  sortKey: WorkspaceSortKey
  sortDirection: WorkspaceSortDirection
  resultCount: number
  selectedReferenceCount: number
  referenceLimit: number
  refreshing: boolean
  onSearchChange: (value: string) => void
  onSortKeyChange: (value: WorkspaceSortKey) => void
  onToggleSortDirection: () => void
}

export function WorkspaceToolbar({
  search, sortKey, sortDirection, resultCount, selectedReferenceCount,
  referenceLimit, refreshing, onSearchChange, onSortKeyChange, onToggleSortDirection
}: WorkspaceToolbarProps) {
  return <div className="space-y-2 border-b border-border px-3 py-2">
    <div className="flex min-w-0 items-center gap-1.5">
      <label className="flex min-w-0 flex-1 items-center gap-1.5 border border-border bg-background-panel px-2">
        <Search size={14} className="shrink-0 text-muted" />
        <input value={search} onChange={(event) => onSearchChange(event.target.value)} className="h-8 min-w-0 flex-1 border-0 bg-transparent p-0 text-xs outline-none" placeholder="搜索当前目录" aria-label="搜索当前目录" />
        {search ? <IconButton label="清空搜索" size="xs" className="hover:bg-transparent" onClick={() => onSearchChange('')}><X size={13} /></IconButton> : null}
      </label>
      <select value={sortKey} onChange={(event) => onSortKeyChange(event.target.value as WorkspaceSortKey)} className="h-8 w-24 shrink-0 border border-border bg-background-panel px-1.5 text-xs text-secondary" aria-label="排序方式">
        <option value="name">按名称</option>
        <option value="modifiedAt">按修改时间</option>
        <option value="size">按大小</option>
      </select>
      <IconButton label={sortDirection === 'asc' ? '切换为降序' : '切换为升序'} size="md" variant="outline" onClick={onToggleSortDirection}>
        {sortDirection === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
      </IconButton>
    </div>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted" aria-live="polite">
      <span>当前结果 {resultCount} 项</span>
      <span>已选引用 {selectedReferenceCount}/{referenceLimit}</span>
      {refreshing ? <span>正在刷新…</span> : null}
    </div>
  </div>
}
