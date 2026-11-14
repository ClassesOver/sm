/** Normal-view page buttons retain native Tab/click semantics; only direct
 * rail focus opts into the fixed source's current-slide navigation keys. */
export function mountSlidesRailNavigation(list: HTMLElement, options: {
  enabled(): boolean
  current(): number
}) {
  let disposed = false
  const keydown = (event: KeyboardEvent) => {
    if (disposed || !options.enabled() || event.defaultPrevented || event.isComposing || event.keyCode === 229 ||
      event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return
    const focused = event.target
    if (!(focused instanceof HTMLButtonElement) || focused !== document.activeElement ||
      !focused.matches('.slide-open[data-slide-index]') || focused.disabled || focused.closest('[hidden],[inert]')) return
    const modalOpen = [...document.querySelectorAll<HTMLElement>('dialog[open],[role="dialog"],[role="alertdialog"]')]
      .some(modal => !modal.closest('[hidden]') && (!(modal instanceof HTMLDialogElement) || modal.open))
    if (modalOpen) return
    if (!['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) return
    const buttons = [...list.querySelectorAll<HTMLButtonElement>('.slide-open[data-slide-index]')]
      .filter(button => !button.disabled && !button.closest('[hidden],[inert]'))
    const index = buttons.findIndex(button => Number(button.dataset.slideIndex) === options.current())
    if (index < 0) return
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
      Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowUp' || event.key === 'PageUp' ? -1 : 1)))
    event.preventDefault()
    if (next === index) return // Do not flush notes again at either boundary.
    const id = Number(buttons[next]!.dataset.slideIndex)
    buttons[next]!.click() // Existing synchronous selection path may veto (e.g. notes.flush).
    if (options.current() !== id) return // Do not steal any error focus set by that veto.
    const target = [...list.querySelectorAll<HTMLButtonElement>('.slide-open[data-slide-index]')]
      .find(button => Number(button.dataset.slideIndex) === id)
    target?.focus({ preventScroll: true })
    target?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }
  list.addEventListener('keydown', keydown)
  return { dispose() { disposed = true; list.removeEventListener('keydown', keydown) } }
}
