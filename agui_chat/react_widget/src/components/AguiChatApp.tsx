import React, { useEffect, useRef, useState } from 'react'
import type { AguiChatProps, AttachmentRef, ErrorMessageProps, RuntimeSnapshot, WorkspaceEntry, WorkspaceReference } from '../types'
import { ChatRuntime } from '../runtime/ChatRuntime'
import { asText } from '../runtime/utils'
import { mergeIcons, mergeLabels, observeInteraction } from '../customization'
import { ChatInput, type ChatInputProps } from './ChatInput'
import { Messages } from './Messages'
import { FilePreviewPanel } from './FilePreviewPanel'
import { Sidebar } from './Sidebar'
import { WorkspacePanel } from './WorkspacePanel'

interface AguiChatAppProps {
  runtime: ChatRuntime
  props: AguiChatProps
}

export function DefaultErrorMessage({ error }: ErrorMessageProps) {
  return <div className="mx-auto mb-2 w-full max-w-3xl px-4 text-sm text-destructive">{error}</div>
}

export function AguiChatApp({ runtime, props }: AguiChatAppProps) {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot>(() => runtime.getSnapshot())
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentRef | null>(null)
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const [workspaceReferences, setWorkspaceReferences] = useState<WorkspaceReference[]>([])
  const [composerMentionCount, setComposerMentionCount] = useState(0)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const followsStream = useRef(true)
  const previousThread = useRef(snapshot.threadId)
  const previousUserCount = useRef(0)
  const labels = mergeLabels(props.labels)
  const icons = mergeIcons(props.icons)

  const scrollVersion = snapshot.messages
    .map((message) =>
      `${message.id}:${String(message.content || '').length}:${message.tool_calls?.length || 0}`
    ).join('|')
  useEffect(() => runtime.subscribe(() => setSnapshot(runtime.getSnapshot())), [runtime])

  useEffect(() => {
    setWorkspaceReferences([])
    setComposerMentionCount(0)
    setPreviewAttachment(null)
    setWorkspaceOpen(false)
  }, [snapshot.threadId])


  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const observer = new MutationObserver(() => {
      if (followsStream.current) element.scrollTop = element.scrollHeight
    })
    observer.observe(element, { childList: true, characterData: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const userCount = snapshot.messages.filter((message) => message.role === 'user').length
    const threadChanged = previousThread.current !== snapshot.threadId
    const userAdded = userCount > previousUserCount.current
    if (threadChanged || userAdded || followsStream.current) {
      element.scrollTop = element.scrollHeight
      followsStream.current = true
    }
    previousThread.current = snapshot.threadId
    previousUserCount.current = userCount
  }, [snapshot.threadId, scrollVersion])

  const handleSend: ChatInputProps['onSend'] = function (
    content, attachments, selection, skills, references
  ) {
    return runtime.send(content, attachments, selection, undefined, skills, references).then(function (sent) {
      if (!sent) return false
      setWorkspaceReferences([])
      const mentions = Array.isArray(selection) ? selection : undefined
      const menuMention = selection && !Array.isArray(selection) ? selection : undefined
      observeInteraction(function () {
        props.onInteraction?.({
          type: 'send', content, attachments, mentions, menuMention, skills, workspaceReferences: references
        })
      })
      return true
    })
  }

  return (
    <div className="agui-chat-react relative">
      <div className="flex h-full min-h-0 overflow-hidden bg-background/90 text-secondary">
        <Sidebar
          snapshot={snapshot}
          initialCollapsed={props.ui?.initialSidebarCollapsed}
          onNewSession={() => void runtime.newSession()}
          onRefreshSessions={() => void runtime.refreshSessions()}
          onLoadSession={(sessionId) => void runtime.loadSession(sessionId)}
          onArchiveSession={(sessionId) => void runtime.archiveSession(sessionId)}
          labels={labels}
        />
        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background-panel">
          <div
            ref={scrollRef}
            className="min-h-0 flex-1 overflow-y-auto"
            onScroll={(event) => {
              const element = event.currentTarget
              followsStream.current =
                element.scrollHeight - element.scrollTop - element.clientHeight <= 24
            }}
          >
            <Messages
              messages={snapshot.messages}
              running={snapshot.running}
              suggestions={props.suggestions}
              toolRenderers={props.toolRenderers}
              labels={labels}
              icons={icons}
              components={props.components}
              hostState={snapshot.hostState}
              onSelectRelation={(tool, candidates) => {
                void runtime.selectRelationCandidates(tool, candidates).then((content) => {
                  if (content) observeInteraction(() => props.onInteraction?.({ type: 'send', content, attachments: [] }))
                })
              }}
              onSelectRecord={(tool, candidate) => {
                void runtime.selectRecordCandidate(tool, candidate).then((content) => {
                  if (content) observeInteraction(() => props.onInteraction?.({
                    type: 'send', content, attachments: [],
                    recordSelection: {
                      ...candidate,
                      snapshotId: snapshot.hostState.snapshotId,
                      hostRevision: snapshot.hostState.hostRevision
                    }
                  }))
                })
              }}
              onRemoveMenuMention={(messageId) => runtime.removeMenuMention(messageId)}
              onRemoveMention={(messageId, referenceId) => runtime.removeMention(messageId, referenceId)}
              onCopy={(message) => {
                const write = navigator.clipboard?.writeText(asText(message.content))
                if (write) void write.catch(() => undefined)
                observeInteraction(() => props.onInteraction?.({ type: 'copy', message }))
              }}
              onFeedback={(message, feedback) => {
                observeInteraction(() => props.onFeedback?.(message, feedback))
                observeInteraction(() => props.onInteraction?.({ type: 'feedback', message, feedback }))
              }}
              onPreviewAttachment={(attachment) => {
                setWorkspaceOpen(false)
                setPreviewAttachment(attachment)
              }}
              onRegenerate={(messageId) => {
                const message = snapshot.messages.find((candidate) => candidate.id === messageId)
                void runtime.regenerate(messageId)
                if (message) observeInteraction(() => props.onInteraction?.({ type: 'regenerate', message }))
              }}
              onSuggestion={(suggestion) => {
                void runtime.send(suggestion.message)
                observeInteraction(() => props.onInteraction?.({ type: 'suggestion', suggestion }))
                observeInteraction(() => props.onInteraction?.({ type: 'send', content: suggestion.message, attachments: [] }))
              }}
              onConfirmTool={(tool, approved) => void runtime.confirmTool(tool, approved)}
              onUndoTool={(tool) => void runtime.undoTool(tool)}
            />
          </div>
          {snapshot.error
            ? React.createElement(props.components?.ErrorMessage || DefaultErrorMessage, { error: snapshot.error })
            : null}
          <ChatInput key={snapshot.threadId}
            running={snapshot.running}
            disabled={snapshot.loadingSessions}
            attachments={props.attachments}
            menuOptions={props.menuOptions || []}
            agentSkills={props.agentSkills || []}
            hostBridge={props.hostBridge}
            workspaceReferences={workspaceReferences}
            onRemoveWorkspaceReference={(id) => setWorkspaceReferences((current) => current.filter((item) => item.id !== id))}
            onMentionsChange={setComposerMentionCount}
            labels={labels}
            icons={icons}
            onSend={handleSend}
            onStop={() => {
              runtime.stop()
              observeInteraction(() => props.onInteraction?.({ type: 'stop' }))
            }}
            onUpload={(file, onProgress) => runtime.uploadAttachment(file, onProgress)}
            onRemove={(attachmentId) => runtime.deleteAttachment(attachmentId)}
            onOpenWorkspace={() => {
              setPreviewAttachment(null)
              setWorkspaceOpen(true)
            }}
          />
        </main>
        {previewAttachment
          ? <FilePreviewPanel
              attachment={previewAttachment}
              labels={labels}
              onClose={() => setPreviewAttachment(null)}
            />
          : null}
        {workspaceOpen
          ? <WorkspacePanel
              runtime={runtime}
              threadId={snapshot.threadId}
              references={workspaceReferences}
              mentionCount={composerMentionCount}
              onToggleReference={(entry: WorkspaceEntry) => setWorkspaceReferences((current) => { const selected = current.some((item) => item.path === entry.path); if (selected) return current.filter((item) => item.path !== entry.path); if (current.length + composerMentionCount >= 5) return current; return [...current, { id: `workspace:${entry.path}`, path: entry.path, name: entry.name, isDirectory: entry.isDirectory }] })}
              onDeleted={(entry: WorkspaceEntry) => setWorkspaceReferences((current) => current.filter((item) => item.path !== entry.path && !(entry.isDirectory && item.path.startsWith(`${entry.path}/`))))}
              onClose={() => setWorkspaceOpen(false)}
            />
          : null}
      </div>
    </div>
  )
}
