const FOCUSABLE =
  ':is(a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),details>summary:first-of-type,[tabindex]:not([tabindex="-1"]))'

export function installFocusTrap(dialog: HTMLElement): () => void {
  const onKeyDown = (event: KeyboardEvent) => {
    if (dialog.hidden || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.key !== 'Tab') return
    const candidates = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (element) => element.offsetParent !== null && element.tabIndex >= 0 && !element.matches(':disabled'),
    )
    const elements = candidates.filter(element => {
      if (!(element instanceof HTMLInputElement) || element.type !== 'radio' || !element.name) return true
      const group = candidates.filter((candidate): candidate is HTMLInputElement =>
        candidate instanceof HTMLInputElement && candidate.type === 'radio' && candidate.name === element.name && candidate.form === element.form)
      return element === (group.find(radio => radio.checked) ?? group[0])
    })
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
