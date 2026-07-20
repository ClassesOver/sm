interface WorkspaceListStateProps {
  loading: boolean
  hasEntries: boolean
  hasVisibleEntries: boolean
  hasError: boolean
  search: string
}

export function WorkspaceListState({
  loading, hasEntries, hasVisibleEntries, hasError, search
}: WorkspaceListStateProps) {
  return <>
    {loading && !hasEntries ? <div role="status" aria-label="正在加载工作区">{Array.from({ length: 5 }).map((_, index) => <div key={index} className="flex h-14 animate-pulse items-center gap-3 border-b border-border/60 px-3"><span className="size-6 bg-background-secondary"/><span className="h-3 flex-1 bg-background-secondary"/></div>)}</div> : null}
    {!loading && !hasError && !hasVisibleEntries ? <div className="grid h-40 place-items-center px-6 text-center text-xs text-muted">{search.trim() ? '没有匹配结果，请尝试其他名称。' : '当前目录为空。'}</div> : null}
  </>
}
