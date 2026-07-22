import { useMemo, useRef } from 'react'
import type {
  AguiChatProps, ChatFeedback, ChatMessage, OdooHostSnapshot, RecordCandidate,
  RelationCandidate, Suggestion, ToolCall
} from '../types'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import { asText } from '../runtime/utils'
import { observeInteraction } from '../customization'
import type { ComposerSend } from './useComposerSubmit'

interface UseChatActionsOptions {
  runtime: ChatRuntime
  props: AguiChatProps
  messages: ChatMessage[]
  hostState: OdooHostSnapshot
  clearWorkspaceReferences: () => void
}

export function useChatActions(options: UseChatActionsOptions) {
  const latest = useRef(options)
  latest.current = options

  return useMemo(() => {
    const send: ComposerSend = (content, attachments, selection, skills, references) => {
      const { runtime, props, clearWorkspaceReferences } = latest.current
      return runtime.send(content, attachments, selection, undefined, skills, references).then((sent) => {
        if (!sent) return false
        clearWorkspaceReferences()
        observeInteraction(() => props.onInteraction?.({
          type: 'send', content, attachments, menuMention: selection, skills,
          workspaceReferences: references
        }))
        return true
      })
    }

    return {
      send,
      newSession: () => { void latest.current.runtime.newSession() },
      refreshSessions: () => { void latest.current.runtime.refreshSessions() },
      loadSession: (sessionId: string | number) => { void latest.current.runtime.loadSession(sessionId) },
      archiveSession: (sessionId: string | number) => { void latest.current.runtime.archiveSession(sessionId) },
      selectRelation: (tool: ToolCall, candidates: RelationCandidate[]) => {
        const { runtime, props } = latest.current
        void runtime.selectRelationCandidates(tool, candidates).then((content) => {
          if (content) observeInteraction(() => props.onInteraction?.({ type: 'send', content, attachments: [] }))
        })
      },
      selectRecord: (tool: ToolCall, candidate: RecordCandidate) => {
        const { runtime, props, hostState } = latest.current
        void runtime.selectRecordCandidate(tool, candidate).then((content) => {
          if (content) observeInteraction(() => props.onInteraction?.({
            type: 'send',
            content,
            attachments: [],
            recordSelection: {
              ...candidate,
              snapshotId: hostState.snapshotId,
              hostRevision: hostState.hostRevision
            }
          }))
        })
      },
      removeMenuMention: (messageId: string) => latest.current.runtime.removeMenuMention(messageId),
      copy: (message: ChatMessage) => {
        const { props } = latest.current
        const write = navigator.clipboard?.writeText(asText(message.content))
        if (write) void write.catch(() => undefined)
        observeInteraction(() => props.onInteraction?.({ type: 'copy', message }))
      },
      feedback: (message: ChatMessage, feedback: ChatFeedback) => {
        const { props } = latest.current
        observeInteraction(() => props.onFeedback?.(message, feedback))
        observeInteraction(() => props.onInteraction?.({ type: 'feedback', message, feedback }))
      },
      regenerate: (messageId: string) => {
        const { runtime, props, messages } = latest.current
        const message = messages.find((candidate) => candidate.id === messageId)
        void runtime.regenerate(messageId)
        if (message) observeInteraction(() => props.onInteraction?.({ type: 'regenerate', message }))
      },
      suggestion: (suggestion: Suggestion) => {
        const { runtime, props } = latest.current
        void runtime.send(suggestion.message)
        observeInteraction(() => props.onInteraction?.({ type: 'suggestion', suggestion }))
        observeInteraction(() => props.onInteraction?.({
          type: 'send', content: suggestion.message, attachments: []
        }))
      },
      confirmTool: (tool: ToolCall, approved: boolean) => {
        void latest.current.runtime.confirmTool(tool, approved)
      },
      undoTool: (tool: ToolCall) => { void latest.current.runtime.undoTool(tool) },
      stop: () => {
        const { runtime, props } = latest.current
        runtime.stop()
        observeInteraction(() => props.onInteraction?.({ type: 'stop' }))
      },
      uploadAttachment: (file: File, onProgress: (progress: number) => void) =>
        latest.current.runtime.uploadAttachment(file, onProgress),
      removeAttachment: (attachmentId: string) => latest.current.runtime.deleteAttachment(attachmentId)
    }
  }, [])
}
