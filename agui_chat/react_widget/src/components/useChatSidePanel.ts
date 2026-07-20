import { useCallback, useEffect, useState } from 'react'
import type { AttachmentRef } from '../types'

export type ChatSidePanelState =
  | { type: 'closed' }
  | { type: 'file'; attachment: AttachmentRef }
  | { type: 'workspace' }

const CLOSED_PANEL: ChatSidePanelState = { type: 'closed' }

export function useChatSidePanel(threadId: string) {
  const [panel, setPanel] = useState<ChatSidePanelState>(CLOSED_PANEL)

  useEffect(() => setPanel(CLOSED_PANEL), [threadId])

  const openFile = useCallback((attachment: AttachmentRef) => {
    setPanel({ type: 'file', attachment })
  }, [])
  const openWorkspace = useCallback(() => {
    setPanel({ type: 'workspace' })
  }, [])
  const closePanel = useCallback(() => {
    setPanel(CLOSED_PANEL)
  }, [])

  return { panel, openFile, openWorkspace, closePanel }
}
