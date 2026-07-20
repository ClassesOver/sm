import type { WorkspaceEntry } from '../types'
import { Button } from './Button'

interface WorkspaceDeleteBarProps {
  entry: WorkspaceEntry | null
  deletingPath: string
  onConfirm: () => void
  onCancel: () => void
}

export function WorkspaceDeleteBar({
  entry, deletingPath, onConfirm, onCancel
}: WorkspaceDeleteBarProps) {
  if (!entry) return null
  const deleting = deletingPath === entry.path

  return <div className="flex min-h-12 items-center gap-2 border-t border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
    <span className="min-w-0 flex-1 break-all" title={entry.path}>删除“{entry.path}”？</span>
    <Button size="sm" variant="danger" className="h-7 shrink-0 rounded-md px-2" disabled={deleting} onClick={onConfirm}>{deleting ? '删除中…' : '确认'}</Button>
    <Button size="sm" className="h-7 shrink-0 rounded-md bg-background-panel px-2" disabled={Boolean(deletingPath)} onClick={onCancel}>取消</Button>
  </div>
}
