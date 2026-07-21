import { useState } from 'react'
import type { Dispatch, RefObject, SetStateAction } from 'react'
import type {
  AttachmentRef, MenuMention, SelectedAgentSkill, WorkspaceReference
} from '../types'

export type ComposerSend = (
  content: string,
  attachments: AttachmentRef[],
  menuMention?: MenuMention,
  skills?: SelectedAgentSkill[],
  workspaceReferences?: WorkspaceReference[]
) => Promise<boolean | void> | boolean | void

interface UseComposerSubmitOptions {
  running: boolean
  disabled: boolean
  value: string
  setValue: Dispatch<SetStateAction<string>>
  attachmentItems: Array<{ status: 'uploading' | 'ready' | 'error' }>
  readyAttachments: AttachmentRef[]
  menuMention?: MenuMention
  selectedSkills: SelectedAgentSkill[]
  workspaceReferences: WorkspaceReference[]
  onSend: ComposerSend
  resetSelections: () => void
  dismissPickers: () => void
  resetAttachments: () => void
  textareaRef: RefObject<HTMLTextAreaElement>
}

export function useComposerSubmit({
  running,
  disabled,
  value,
  setValue,
  attachmentItems,
  readyAttachments,
  menuMention,
  selectedSkills,
  workspaceReferences,
  onSend,
  resetSelections,
  dismissPickers,
  resetAttachments,
  textareaRef
}: UseComposerSubmitOptions) {
  const [sending, setSending] = useState(false)
  const canSend = !running && !sending && !disabled &&
    !attachmentItems.some((item) => item.status !== 'ready') &&
    (!!value.trim() || readyAttachments.length > 0 || !!menuMention ||
      selectedSkills.length > 0 || workspaceReferences.length > 0)

  const submit = async () => {
    if (!canSend) return
    const content = value.trim()
    setSending(true)
    let sent: boolean | void = false
    try {
      sent = await Promise.resolve(selectedSkills.length
        ? onSend(
            content,
            readyAttachments,
            menuMention,
            selectedSkills.map((skill) => ({ ...skill })),
            workspaceReferences.map((reference) => ({ ...reference }))
          )
        : onSend(
            content,
            readyAttachments,
            menuMention,
            undefined,
            workspaceReferences.map((reference) => ({ ...reference }))
          ))
    } catch (_error) {
      sent = false
    } finally {
      setSending(false)
    }
    if (sent === false) return
    setValue('')
    resetSelections()
    dismissPickers()
    resetAttachments()
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  return { sending, canSend, submit }
}
