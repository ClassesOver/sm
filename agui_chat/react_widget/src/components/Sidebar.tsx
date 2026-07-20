import { ChevronsLeft, ChevronsRight, MessageSquarePlus, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ChatLabels, RuntimeSnapshot } from '../types'
import { cn } from '../lib'
import { Button } from './Button'
import { SessionItem } from './SessionItem'

interface SidebarProps {
  snapshot: RuntimeSnapshot
  initialCollapsed?: boolean
  onNewSession: () => void
  onRefreshSessions: () => void
  onLoadSession: (sessionId: string | number) => void
  onArchiveSession: (sessionId: string | number) => void
  labels: ChatLabels
}

export function Sidebar({
  snapshot,
  initialCollapsed,
  onNewSession,
  onRefreshSessions,
  onLoadSession,
  onArchiveSession,
  labels
}: SidebarProps) {
  const [collapsed, setCollapsed] = useState(!!initialCollapsed)
  const [confirmArchive, setConfirmArchive] = useState<string | number | null>(null)
  const currentSessionId = snapshot.session?.id
  const sortedSessions = useMemo(() => snapshot.sessions || [], [snapshot.sessions])

  return (
    <>
    {!collapsed ? (
      <button
        type="button"
        className="absolute inset-0 z-20 hidden border-0 bg-primary/10 p-0 max-md:block"
        aria-label="关闭侧栏"
        onClick={() => setCollapsed(true)}
      />
    ) : null}
    {collapsed ? (
      <>
        <div
          aria-hidden="true"
          className="absolute inset-y-0 left-0 z-10 w-1 border-r border-border bg-accent shadow-[1px_0_0_rgba(15,23,42,0.04)]"
        />
        <Button
          variant="ghost"
          size="icon"
          className="absolute left-2 top-2 z-20 size-9 border border-border bg-background-panel text-primary shadow-md transition-colors hover:border-primary/30 hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40"
          onClick={() => setCollapsed(false)}
          aria-label="展开侧栏"
          title="展开侧栏"
        >
          <ChevronsRight className="size-4" />
        </Button>
      </>
    ) : null}
    <aside
      className={cn(
        'relative flex h-full shrink-0 flex-col overflow-hidden border-r border-border bg-background px-2 py-3 transition-[width]',
        collapsed ? 'w-0 border-r-0 p-0' : 'w-64 max-md:absolute max-md:inset-y-0 max-md:z-30 max-md:shadow-xl'
      )}
    >
      {!collapsed ? <Button
        variant="ghost"
        size="icon"
        className="absolute right-1.5 top-2 z-10 size-8 border border-border bg-background-panel text-primary shadow-sm transition-colors hover:border-primary/30 hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40"
        onClick={() => setCollapsed((value) => !value)}
        aria-label="收起侧栏"
      >
        <ChevronsLeft className="size-4" />
      </Button> : null}

      <div
        className={cn(
          'flex min-w-60 flex-col gap-5 transition-opacity',
          collapsed ? 'pointer-events-none opacity-0' : 'opacity-100'
        )}
      >
        <div className="flex items-center gap-2 pr-9">
          <div className="grid size-7 place-items-center rounded-lg bg-brand text-xs font-semibold text-white">
            AG
          </div>
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold uppercase text-primary">智能助手</div>
          </div>
        </div>

        <Button
          variant="primary"
          className="h-9 w-full text-xs font-semibold uppercase"
          onClick={onNewSession}
          disabled={snapshot.running || snapshot.loadingSessions}
        >
          <MessageSquarePlus className="size-4" />
          {labels.newSession}
        </Button>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="text-xs font-medium uppercase text-primary">会话</div>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              onClick={onRefreshSessions}
              disabled={snapshot.loadingSessions}
              aria-label="刷新会话"
            >
              <RefreshCw className={cn('size-3.5', snapshot.loadingSessions && 'animate-spin')} />
            </Button>
          </div>
          <div className="max-h-[calc(100vh-235px)] min-h-32 overflow-y-auto pr-1">
            {sortedSessions.length ? (
              <div className="flex flex-col gap-1">
                {sortedSessions.map((session) => {
                  const selected = session.id === currentSessionId
                  return <SessionItem
                    key={session.id}
                    session={session}
                    selected={selected}
                    confirmingArchive={confirmArchive === session.id}
                    onLoad={onLoadSession}
                    onRequestArchive={setConfirmArchive}
                    onConfirmArchive={(sessionId) => { onArchiveSession(sessionId); setConfirmArchive(null) }}
                    onCancelArchive={() => setConfirmArchive(null)}
                  />
                })}
              </div>
            ) : (
              <div className="rounded-lg border border-border bg-accent p-3 text-sm text-muted">
                暂无会话
              </div>
            )}
          </div>
        </div>

      </div>
    </aside>
    </>
  )
}
