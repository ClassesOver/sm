import { ChevronRight } from 'lucide-react'

interface WorkspaceBreadcrumbsProps {
  path: string
  onNavigate: (path: string) => void
}

export function WorkspaceBreadcrumbs({ path, onNavigate }: WorkspaceBreadcrumbsProps) {
  const parts = path ? path.split('/') : []
  const items = [{ label: '工作区', path: '' }, ...parts.map((part, index) => ({
    label: part,
    path: parts.slice(0, index + 1).join('/')
  }))]

  return <nav className="flex min-h-9 flex-wrap items-center gap-1 border-b border-border bg-background-panel px-3 py-1.5" aria-label="工作区路径">
    {items.map((item, index) => <span key={item.path || 'root'} className="inline-flex min-w-0 items-center gap-1">
      {index ? <ChevronRight size={12} className="text-muted" /> : null}
      <button type="button" className="max-w-36 truncate border-0 bg-transparent p-0 text-xs text-secondary transition-colors hover:text-primary focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/30" title={item.label} onClick={() => onNavigate(item.path)}>{item.label}</button>
    </span>)}
  </nav>
}
