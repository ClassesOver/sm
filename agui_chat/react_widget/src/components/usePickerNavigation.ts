import { useCallback, useState } from 'react'
import type { KeyboardEvent } from 'react'

interface UsePickerNavigationOptions {
  open: boolean
  optionCount: number
  allowHomeEnd?: boolean
  allowSpace?: boolean
  captureEmptyActivation?: boolean
}

export function usePickerNavigation({
  open, optionCount, allowHomeEnd = false, allowSpace = false, captureEmptyActivation = false
}: UsePickerNavigationOptions) {
  const [activeIndex, setActiveIndex] = useState(0)
  const resetActiveIndex = useCallback(() => setActiveIndex(0), [])

  const handleKey = useCallback((
    event: KeyboardEvent<HTMLElement>,
    onActivate: (index: number) => void,
    onEscape: () => void
  ): boolean => {
    if (!open || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') {
      event.preventDefault()
      onEscape()
      return true
    }
    if (allowHomeEnd && (event.key === 'Home' || event.key === 'End')) {
      event.preventDefault()
      setActiveIndex(event.key === 'Home' ? 0 : Math.max(0, optionCount - 1))
      return true
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((current) => optionCount ? (current + delta + optionCount) % optionCount : 0)
      return true
    }
    const activates = event.key === 'Enter' || (allowSpace && event.key === ' ')
    if (activates && (optionCount > 0 || captureEmptyActivation)) {
      event.preventDefault()
      onActivate(activeIndex)
      return true
    }
    return false
  }, [activeIndex, allowHomeEnd, allowSpace, captureEmptyActivation, open, optionCount])

  return { activeIndex, resetActiveIndex, handleKey }
}
