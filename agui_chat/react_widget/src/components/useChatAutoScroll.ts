import { useCallback, useEffect, useRef } from 'react'
import type { UIEvent } from 'react'
import type { ChatMessage } from '../types'

export function useChatAutoScroll(threadId: string, messages: ChatMessage[]) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const followsStream = useRef(true)
  const previousThread = useRef(threadId)
  const previousUserCount = useRef(0)
  const userCount = messages.reduce((count, message) => count + (message.role === 'user' ? 1 : 0), 0)

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
    const threadChanged = previousThread.current !== threadId
    const userAdded = userCount > previousUserCount.current
    if (threadChanged || userAdded || followsStream.current) {
      element.scrollTop = element.scrollHeight
      followsStream.current = true
    }
    previousThread.current = threadId
    previousUserCount.current = userCount
  }, [threadId, userCount])

  const handleScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget
    followsStream.current = element.scrollHeight - element.scrollTop - element.clientHeight <= 24
  }, [])

  return { scrollRef, handleScroll }
}
