import { ArrowDown, ArrowUp, ChevronDown, Search, SlidersHorizontal, X } from 'lucide-react'
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
  return <div className="space-y-2 border-b border-border bg-background px-3 py-2">
    <div className="flex min-w-0 items-center gap-1.5">
      <label className="flex min-w-0 flex-1 items-center gap-1.5 border border-border bg-background-panel px-2 outline outline-1 outline-border/70 transition-colors focus-within:border-primary/30 focus-within:outline-primary/25 focus-within:ring-2 focus-within:ring-primary/5">
        <Search size={14} className="shrink-0 text-muted" />
        <input value={search} onChange={(event) => onSearchChange(event.target.value)} className="h-8 min-w-0 flex-1 border-0 bg-transparent p-0 text-xs outline-none" placeholder="搜索当前目录" aria-label="搜索当前目录" />
        {search ? <IconButton label="清空搜索" size="xs" className="hover:bg-transparent" onClick={() => onSearchChange('')}><X size={13} /></IconButton> : null}
      </label>
      <div className="flex h-8 shrink-0 items-center overflow-hidden rounded-md border border-muted/35 bg-background-panel shadow-[0_1px_2px_rgba(15,23,42,0.08)] outline outline-1 outline-border/70 transition-colors hover:border-muted/55 hover:outline-muted/45 has-[:focus-visible]:border-primary/35 has-[:focus-visible]:outline-primary/25 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary/10">
        <SlidersHorizontal size={13} className="ml-2 shrink-0 text-muted" aria-hidden="true" />
        <div className="relative">
          <select value={sortKey} onChange={(event) => onSortKeyChange(event.target.value as WorkspaceSortKey)} className="h-8 w-[5.5rem] appearance-none border-0 bg-transparent py-0 pl-1.5 pr-5 text-xs text-secondary outline-none" aria-label="排序方式">
            <option value="name">按名称</option>
            <option value="modifiedAt">按修改时间</option>
            <option value="size">按大小</option>
          </select>
          <ChevronDown size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
        </div>
        <IconButton label={sortDirection === 'asc' ? '切换为降序' : '切换为升序'} title={sortDirection === 'asc' ? '升序，切换为降序' : '降序，切换为升序'} size="md" variant="ghost" className="rounded-none border-0 bg-background-secondary text-primary outline outline-1 outline-border/70 hover:bg-border/70 hover:text-primary focus-visible:-outline-offset-2" onClick={onToggleSortDirection}>
          {sortDirection === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
        </IconButton>
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted" aria-live="polite">
      <span className="text-secondary">当前结果 {resultCount} 项</span>
      <span>已选引用 {selectedReferenceCount}/{referenceLimit}</span>
      {refreshing ? <span>正在刷新…</span> : null}
    </div>
  </div>
}
