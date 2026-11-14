import { useEffect, useRef, type KeyboardEvent } from 'react'
import { installFocusTrap } from './focus-trap'

/** 源 modal 行为加上输入法保护与原生焦点恢复。 */
export function useModalKeys(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const container = ref.current, previous = document.activeElement as HTMLElement | null
    if (!container) return
    if (!container.contains(document.activeElement)) container.querySelector<HTMLElement>('input,select,button')?.focus()
    const release = installFocusTrap(container)
    return () => { release(); if (previous?.isConnected) previous.focus() }
  }, [])
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose() }
  }
  return { ref, onKeyDown }
}
