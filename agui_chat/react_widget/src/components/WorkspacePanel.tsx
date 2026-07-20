import { Folder, RefreshCw } from 'lucide-react'
import { useCallback } from 'react'
import type { WorkspaceEntry, WorkspaceReference } from '../types'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import { cn } from '../lib'
import { AsidePanel } from './AsidePanel'
import { Button } from './Button'
import { IconButton } from './IconButton'
import { InlineNotice } from './InlineNotice'
import { WorkspaceEntryRow } from './WorkspaceEntryRow'
import { WorkspaceBreadcrumbs } from './WorkspaceBreadcrumbs'
import { WorkspaceDeleteBar } from './WorkspaceDeleteBar'
import { WorkspaceFilePreview } from './WorkspaceFilePreview'
import { WorkspaceListState } from './WorkspaceListState'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { useWorkspaceDirectory } from './useWorkspaceDirectory'
import { useWorkspacePreview } from './useWorkspacePreview'

interface WorkspacePanelProps {
  runtime: ChatRuntime
  threadId: string
  references: WorkspaceReference[]
  onToggleReference: (entry: WorkspaceEntry) => void
  onDeleted: (entry: WorkspaceEntry) => void
  onClose: () => void
}

export function WorkspacePanel({ runtime, threadId, references, onToggleReference, onDeleted, onClose }: WorkspacePanelProps) {
  const preview = useWorkspacePreview(runtime)
  const handleDeleted = useCallback((entry: WorkspaceEntry) => {
    onDeleted(entry)
    preview.closeRelatedPreview(entry)
  }, [onDeleted, preview.closeRelatedPreview])
  const directory = useWorkspaceDirectory({
    runtime,
    threadId,
    references,
    onToggleReference,
    onDeleted: handleDeleted
  })
  const navigate = useCallback((nextPath: string) => {
    directory.navigate(nextPath)
    preview.closePreview()
  }, [directory.navigate, preview.closePreview])
  const openPreview = useCallback((entry: WorkspaceEntry) => {
    directory.clearMessages()
    void preview.openPreview(entry)
  }, [directory.clearMessages, preview.openPreview])

  return <AsidePanel
    ariaLabel="聊天工作区"
    eyebrow="当前对话"
    title="工作区"
    icon={<Folder size={14} />}
    closeLabel="关闭工作区"
    onClose={onClose}
    actions={<IconButton label="刷新工作区" size="md" variant="outline" disabled={directory.loading} onClick={() => void directory.load(true)}><RefreshCw size={15} className={cn(directory.loading && 'animate-spin')} /></IconButton>}
    className="agui-workspace-aside"
  >
    <div className="flex h-full min-h-0 flex-col">
      <WorkspaceBreadcrumbs path={directory.path} onNavigate={navigate} />
      {directory.listError ? <InlineNotice tone="error" variant="band" action={<Button variant="ghost" size="sm" className="h-auto shrink-0 border-0 bg-transparent p-0 font-medium text-current underline hover:bg-transparent hover:text-current" onClick={() => void directory.load(directory.entries.length > 0)}>重试</Button>}>{directory.listError}</InlineNotice> : null}
      {directory.actionError ? <InlineNotice tone="error" variant="band">{directory.actionError}</InlineNotice> : null}
      {directory.notice ? <InlineNotice tone="warning" variant="band">{directory.notice}</InlineNotice> : null}
      {preview.preview ? <WorkspaceFilePreview preview={preview.preview} onDownload={directory.download} onClose={preview.closePreview} /> : <>
        <WorkspaceToolbar
          search={directory.search}
          sortKey={directory.sortKey}
          sortDirection={directory.sortDirection}
          resultCount={directory.visibleEntries.length}
          selectedReferenceCount={references.length}
          referenceLimit={directory.referenceLimit}
          refreshing={directory.loading && directory.entries.length > 0}
          onSearchChange={directory.setSearch}
          onSortKeyChange={directory.setSortKey}
          onToggleSortDirection={directory.toggleSortDirection}
        />
        <div className="min-h-0 flex-1 overflow-y-auto" role="list" aria-label="工作区文件" aria-busy={directory.loading}>
          <WorkspaceListState
            loading={directory.loading}
            hasEntries={directory.entries.length > 0}
            hasVisibleEntries={directory.visibleEntries.length > 0}
            hasError={Boolean(directory.listError)}
            search={directory.search}
          />
          {directory.visibleEntries.map((entry) => {
            const selected = references.some((item) => item.path === entry.path)
            return <WorkspaceEntryRow
              key={entry.path}
              entry={entry}
              selected={selected}
              atReferenceLimit={!selected && references.length >= directory.referenceLimit}
              deleting={Boolean(directory.deletingPath)}
              onToggleReference={directory.toggleReference}
              onOpen={(item) => item.isDirectory ? navigate(item.path) : openPreview(item)}
              onPreview={openPreview}
              onDownload={directory.download}
              onDelete={directory.requestDelete}
            />
          })}
        </div>
      </>}
      <WorkspaceDeleteBar
        entry={directory.confirmDelete}
        deletingPath={directory.deletingPath}
        onConfirm={() => void directory.remove()}
        onCancel={directory.cancelDelete}
      />
    </div>
  </AsidePanel>
}
