import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent
} from 'react'

const KEYBOARD_STEP = 24

interface UseAsideResizeOptions {
  defaultWidth: number
  minWidth: number
  maxWidth: number
  minMainWidth: number
}

export function useAsideResize({
  defaultWidth, minWidth, maxWidth, minMainWidth
}: UseAsideResizeOptions) {
  const panelRef = useRef<HTMLElement | null>(null)
  const activeResizeCleanup = useRef<(() => void) | null>(null)
  const [width, setWidth] = useState(defaultWidth)

  const clampWidth = useCallback((nextWidth: number) => {
    const panel = panelRef.current
    let main = panel?.previousElementSibling
    while (main?.classList.contains('agui-aside-backdrop')) main = main.previousElementSibling
    const available = main instanceof HTMLElement && panel
      ? main.getBoundingClientRect().width + panel.getBoundingClientRect().width
      : Number.POSITIVE_INFINITY
    const availableMax = Math.max(minWidth, available - minMainWidth)
    return Math.min(Math.max(nextWidth, minWidth), maxWidth, availableMax)
  }, [maxWidth, minMainWidth, minWidth])

  const stopActiveResize = useCallback(() => {
    activeResizeCleanup.current?.()
  }, [])

  useEffect(() => stopActiveResize, [stopActiveResize])

  const handleResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault()
    stopActiveResize()
    const startX = event.clientX
    const startWidth = panelRef.current?.getBoundingClientRect().width || width
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handlePointerMove = (moveEvent: PointerEvent) => {
      setWidth(clampWidth(startWidth + startX - moveEvent.clientX))
    }
    const cleanup = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', cleanup)
      if (activeResizeCleanup.current === cleanup) activeResizeCleanup.current = null
    }
    activeResizeCleanup.current = cleanup
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', cleanup, { once: true })
  }, [clampWidth, stopActiveResize, width])

  const handleResizeKeyDown = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setWidth((current) => clampWidth(current + KEYBOARD_STEP))
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      setWidth((current) => clampWidth(current - KEYBOARD_STEP))
    }
  }, [clampWidth])

  return {
    panelRef,
    style: { '--agui-aside-width': `${width}px` } as CSSProperties,
    handleResizeStart,
    handleResizeKeyDown
  }
}
