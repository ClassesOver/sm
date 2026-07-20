import React from 'react'
import type {
  AssistantMessageProps, AttachmentRef, ChatComponents, ChatFeedback, ChatIcons,
    ChatLabels, ChatMessage, OdooHostSnapshot, RecordCandidate, RelationCandidate,
    Suggestion, ToolCall, ToolRenderer, UserMessageProps, X2ManyImportPreviewRequest,
    X2ManyImportPreviewResponse
} from '../types'
import { AssistantMessageControls } from './AssistantMessageControls'
import { InlineNotice } from './InlineNotice'
import { Markdown } from './Markdown'
import { MessageAttachments } from './MessageAttachments'
import { MessageContextBar } from './MessageContextBar'
import { MessageReasoning } from './MessageReasoning'
import { MessageReferences } from './MessageReferences'
import { SuggestionList } from './SuggestionList'
import { ToolCallCard } from './ToolCallCard'
import {
  getAssistantMessagePresentation,
  getMessageListPresentation,
  getToolCallRenderKey,
  getUserMessageContent,
  normalizeMessageRole
} from './messagePresentation'
import { useMessageFeedback } from './useMessageFeedback'

export interface MessagesProps {
  messages: ChatMessage[]
  running: boolean
  onConfirmTool: (tool: ToolCall, approved: boolean) => void
  onUndoTool?: (tool: ToolCall) => void
  onPreviewX2ManyImport?: (
    tool: ToolCall,
    request: X2ManyImportPreviewRequest
  ) => Promise<X2ManyImportPreviewResponse>
  suggestions?: Suggestion[]
  toolRenderers?: Record<string, ToolRenderer>
  onRegenerate: (messageId: string) => void
  onSuggestion: (suggestion: Suggestion) => void
  labels: ChatLabels
  icons: ChatIcons
  components?: ChatComponents
  onCopy: (message: ChatMessage) => void
  onFeedback: (message: ChatMessage, feedback: ChatFeedback) => void
  onPreviewAttachment: (attachment: AttachmentRef) => void
  hostState: OdooHostSnapshot
  onSelectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => void
  onSelectRecord: (tool: ToolCall, candidate: RecordCandidate) => void
  onRemoveMenuMention?: (messageId: string) => void
  onRemoveMention?: (messageId: string, referenceId: string) => void
}

export function DefaultAssistantMessage({
  message, running, isCurrent, toolRenderers, labels, icons, hostState,
  onCopy, onRegenerate, onConfirmTool, onUndoTool = () => undefined,
  onPreviewX2ManyImport, onSelectRelation, onSelectRecord
}: AssistantMessageProps) {
  const { content, reasoning, references, canRegenerate } = getAssistantMessagePresentation(message)
  return <div className="flex flex-col gap-5">
    <MessageReasoning steps={reasoning} />
    <MessageReferences references={references} />
    {message.tool_calls?.length ? <div className="flex flex-col gap-2">{message.tool_calls.map((tool, index) => (
      <ToolCallCard key={getToolCallRenderKey(tool, index)} tool={tool} renderers={toolRenderers} labels={labels} hostState={hostState} running={running} onSelectRelation={onSelectRelation} onSelectRecord={onSelectRecord} onConfirm={(approved) => onConfirmTool(tool, approved)} onUndo={() => onUndoTool(tool)} onPreviewX2ManyImport={onPreviewX2ManyImport ? (request) => onPreviewX2ManyImport(tool, request) : undefined} />
    ))}</div> : null}
    {content || message.streaming_error ? <div className="group flex items-start gap-3">
      <div className="grid size-6 shrink-0 place-items-center rounded bg-primary text-primaryAccent">{icons.assistant}</div>
      <div className="min-w-0 flex-1">
        {message.streaming_error ? <InlineNotice className="mb-3 p-3 text-sm" tone="error">{message.streaming_error}</InlineNotice> : null}
        {content ? <Markdown>{content}</Markdown> : null}
        <AssistantMessageControls
          isCurrent={isCurrent}
          running={running}
          canRegenerate={canRegenerate}
          labels={labels}
          icons={icons}
          onCopy={onCopy}
          onRegenerate={onRegenerate}
        />
      </div>
    </div> : null}
  </div>
}

export function DefaultUserMessage({ message, labels, onPreviewAttachment, onRemoveMenuMention, onRemoveMention }: UserMessageProps) {
  const content = getUserMessageContent(message)
  return <div className="flex w-full justify-end">
    <div className="min-w-0 max-w-[82%]">
      <MessageAttachments attachments={message.attachments} labels={labels} onPreview={onPreviewAttachment} />
      <MessageContextBar
        mentions={message.mentions}
        workspaceReferences={message.workspaceReferences}
        skills={message.skills}
        menuMention={message.menuMention}
        onRemoveMention={onRemoveMention}
        onRemoveMenuMention={onRemoveMenuMention}
      />
      {content ? <div className="ml-auto w-fit rounded-lg bg-background-secondary px-3.5 py-2 text-sm leading-6 text-secondary">{content}</div> : null}
    </div>
  </div>
}

export function Messages({
  messages, running, suggestions, toolRenderers, labels, icons, components,
  onRegenerate, onSuggestion, onConfirmTool, onUndoTool, onCopy, onFeedback, onPreviewAttachment,
  hostState, onSelectRelation, onSelectRecord, onPreviewX2ManyImport,
  onRemoveMenuMention, onRemoveMention
}: MessagesProps) {
  const messageFeedback = useMessageFeedback(onFeedback)
  const { displayMessages, lastAssistantIndex } = getMessageListPresentation(messages)
  const AssistantMessage = components?.AssistantMessage || DefaultAssistantMessage
  const UserMessage = components?.UserMessage || DefaultUserMessage
  if (!displayMessages.length) return <div className="flex min-h-[320px] flex-col items-center justify-center px-4 text-center">
    <div className="grid size-12 place-items-center rounded-xl bg-accent text-primary">{icons.assistant}</div>
    <div className="mt-4 text-sm font-medium text-primary">{labels.emptyTitle}</div>
    <div className="mt-1 mb-5 max-w-sm text-sm text-muted">{labels.emptyDescription}</div>
    <SuggestionList suggestions={suggestions} disabled={running} onSelect={onSuggestion} />
  </div>
  return <div className="mx-auto flex w-full max-w-3xl flex-col gap-12 px-4 py-8">
    {displayMessages.map((message, index) => {
      const role = normalizeMessageRole(message.role)
      if (role === 'assistant') return <AssistantMessage key={message.id || `assistant-${index}`} message={message} running={running} isCurrent={index === lastAssistantIndex} toolRenderers={toolRenderers} labels={labels} icons={icons} feedback={messageFeedback.feedback[message.id] || null} hostState={hostState} onSelectRelation={(tool, candidates) => onSelectRelation(tool, candidates)} onSelectRecord={(tool, candidate) => onSelectRecord(tool, candidate)} onCopy={() => onCopy(message)} onRegenerate={() => onRegenerate(message.id)} onFeedback={(next) => messageFeedback.toggleFeedback(message, next)} onConfirmTool={onConfirmTool} onUndoTool={(tool) => onUndoTool?.(tool)} onPreviewX2ManyImport={onPreviewX2ManyImport} />
      if (role === 'user') return <UserMessage key={message.id || `user-${index}`} message={message} icons={icons} labels={labels} onPreviewAttachment={onPreviewAttachment} onRemoveMenuMention={message.menuMention && onRemoveMenuMention ? () => onRemoveMenuMention(message.id) : undefined} onRemoveMention={message.mentions?.length && onRemoveMention ? (referenceId) => onRemoveMention(message.id, referenceId) : undefined} />
      return null
    })}
    {running ? <div className="agui-activity flex items-center gap-1.5 py-1" aria-label={labels.generatingResponse}>{[0, 1, 2].map((index) => <React.Fragment key={index}>{icons.activity}</React.Fragment>)}</div> : <SuggestionList suggestions={suggestions} disabled={false} onSelect={onSuggestion} />}
  </div>
}
