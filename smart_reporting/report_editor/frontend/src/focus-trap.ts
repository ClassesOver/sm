const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

export function installFocusTrap(dialog: HTMLElement): () => void {
  const onKeyDown = (event: KeyboardEvent) => {
    if (dialog.hidden || event.key !== 'Tab') return
    const elements = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (element) => element.offsetParent !== null,
    )
    if (!elements.length) return
    const first = elements[0]
    const last = elements[elements.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }
  dialog.addEventListener('keydown', onKeyDown)
  return () => dialog.removeEventListener('keydown', onKeyDown)
}
