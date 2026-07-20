import React from 'react'
import type { AguiChatProps, ErrorMessageProps } from '../types'
import { ChatRuntime } from '../runtime/ChatRuntime'
import { mergeIcons, mergeLabels } from '../customization'
import { ChatInput } from './ChatInput'
import { Messages } from './Messages'
import { FilePreviewPanel } from './FilePreviewPanel'
import { Sidebar } from './Sidebar'
import { WorkspacePanel } from './WorkspacePanel'
import { useChatAutoScroll } from './useChatAutoScroll'
import { useChatActions } from './useChatActions'
import { useChatSidePanel } from './useChatSidePanel'
import { useRuntimeSnapshot } from './useRuntimeSnapshot'
import { useWorkspaceReferences } from './useWorkspaceReferences'

interface AguiChatAppProps {
  runtime: ChatRuntime
  props: AguiChatProps
}

export function DefaultErrorMessage({ error }: ErrorMessageProps) {
  return <div className="mx-auto mb-2 w-full max-w-3xl px-4 text-sm text-destructive">{error}</div>
}

export function AguiChatApp({ runtime, props }: AguiChatAppProps) {
  const snapshot = useRuntimeSnapshot(runtime)
  const labels = mergeLabels(props.labels)
  const icons = mergeIcons(props.icons)
  const chatScroll = useChatAutoScroll(snapshot.threadId, snapshot.messages)
  const sidePanel = useChatSidePanel(snapshot.threadId)
  const workspace = useWorkspaceReferences(snapshot.threadId)
  const actions = useChatActions({
    runtime,
    props,
    messages: snapshot.messages,
    hostState: snapshot.hostState,
    clearWorkspaceReferences: workspace.clearReferences
  })

  return (
    <div className="agui-chat-react relative">
      <div className="flex h-full min-h-0 overflow-hidden bg-background/90 text-secondary">
        <Sidebar
          snapshot={snapshot}
          initialCollapsed={props.ui?.initialSidebarCollapsed}
          onNewSession={actions.newSession}
          onRefreshSessions={actions.refreshSessions}
          onLoadSession={actions.loadSession}
          onArchiveSession={actions.archiveSession}
          labels={labels}
        />
        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background-panel">
          <div
            ref={chatScroll.scrollRef}
            className="min-h-0 flex-1 overflow-y-auto"
            onScroll={chatScroll.handleScroll}
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
              onSelectRelation={actions.selectRelation}
              onSelectRecord={actions.selectRecord}
              onRemoveMenuMention={actions.removeMenuMention}
              onRemoveMention={actions.removeMention}
              onCopy={actions.copy}
              onFeedback={actions.feedback}
              onPreviewAttachment={sidePanel.openFile}
              onRegenerate={actions.regenerate}
              onSuggestion={actions.suggestion}
              onConfirmTool={actions.confirmTool}
              onUndoTool={actions.undoTool}
            />
          </div>
          {snapshot.error
            ? React.createElement(props.components?.ErrorMessage || DefaultErrorMessage, { error: snapshot.error })
            : null}
          <ChatInput key={snapshot.threadId}
            running={snapshot.running}
            disabled={snapshot.loadingSessions}
            attachments={props.attachments}
            menuOptions={props.menuOptions}
            agentSkills={props.agentSkills}
            hostBridge={props.hostBridge}
            workspaceReferences={workspace.references}
            onRemoveWorkspaceReference={workspace.removeReference}
            labels={labels}
            icons={icons}
            onSend={actions.send}
            onStop={actions.stop}
            onUpload={actions.uploadAttachment}
            onRemove={actions.removeAttachment}
            onOpenWorkspace={sidePanel.openWorkspace}
          />
        </main>
        {sidePanel.panel.type === 'file'
          ? <FilePreviewPanel
              attachment={sidePanel.panel.attachment}
              labels={labels}
              onClose={sidePanel.closePanel}
            />
          : null}
        {sidePanel.panel.type === 'workspace'
          ? <WorkspacePanel
              runtime={runtime}
              threadId={snapshot.threadId}
              references={workspace.references}
              onToggleReference={workspace.toggleReference}
              onDeleted={workspace.removeDeleted}
              onClose={sidePanel.closePanel}
            />
          : null}
      </div>
    </div>
  )
}
