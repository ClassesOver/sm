import { useCallback, useEffect, useRef, useState } from 'react'

const DEFAULT_DURATION = 1400

export function useCopyFeedback(copyAction: () => Promise<void> | void, duration = DEFAULT_DURATION) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)
  const mounted = useRef(true)
  const actionRef = useRef(copyAction)
  actionRef.current = copyAction

  const clearTimer = useCallback(() => {
    if (timer.current === null) return
    window.clearTimeout(timer.current)
    timer.current = null
  }, [])

  const copy = useCallback(async () => {
    await actionRef.current()
    if (!mounted.current) return
    clearTimer()
    setCopied(true)
    timer.current = window.setTimeout(() => {
      timer.current = null
      setCopied(false)
    }, duration)
  }, [clearTimer, duration])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      clearTimer()
    }
  }, [clearTimer])

  return { copied, copy }
}
