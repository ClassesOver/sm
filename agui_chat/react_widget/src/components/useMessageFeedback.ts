import { useCallback, useRef, useState } from 'react'
import type { ChatFeedback, ChatMessage } from '../types'

type FeedbackChoice = Exclude<ChatFeedback, null>

export function useMessageFeedback(
  onFeedback: (message: ChatMessage, feedback: ChatFeedback) => void
) {
  const [feedback, setFeedback] = useState<Record<string, ChatFeedback>>({})
  const feedbackRef = useRef(feedback)
  const onFeedbackRef = useRef(onFeedback)
  feedbackRef.current = feedback
  onFeedbackRef.current = onFeedback

  const toggleFeedback = useCallback((message: ChatMessage, choice: FeedbackChoice) => {
    const value = feedbackRef.current[message.id] === choice ? null : choice
    const next = { ...feedbackRef.current, [message.id]: value }
    feedbackRef.current = next
    setFeedback(next)
    onFeedbackRef.current(message, value)
  }, [])

  return { feedback, toggleFeedback }
}
