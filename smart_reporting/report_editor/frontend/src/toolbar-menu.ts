/** Shared application menu; actions keep their original buttons and listeners. */
export function createMoreActionsController(root: HTMLElement, toggle: HTMLButtonElement) {
  const menu = root.querySelector<HTMLElement>('.secondary-actions')
  const buttons = () => [...(menu?.querySelectorAll<HTMLButtonElement>('button:not([disabled]):not([hidden])') ?? [])]
  const close = (restoreFocus = false) => {
    root.classList.remove('more-actions-open')
    toggle.setAttribute('aria-expanded', 'false')
    if (menu) menu.hidden = true
    if (restoreFocus) toggle.focus()
  }
  close()
  toggle.setAttribute('aria-haspopup', 'true')
  const open = () => {
    if (!menu) return
    document.dispatchEvent(new CustomEvent('report-panel-open', { detail: 'toolbar-menu' }))
    root.classList.add('more-actions-open'); toggle.setAttribute('aria-expanded', 'true'); menu.hidden = false
    const rect = toggle.getBoundingClientRect()
    menu.style.left = `${Math.max(8, Math.min(rect.right - 224, window.innerWidth - 240))}px`
    menu.style.top = `${Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - menu.offsetHeight - 8))}px`
    buttons()[0]?.focus()
  }
  toggle.addEventListener('click', event => {
    event.stopPropagation()
    if (toggle.getAttribute('aria-expanded') === 'true') close(true); else open()
  })
  toggle.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); open() }
  })
  menu?.addEventListener('click', event => {
    if ((event.target as Element).closest('button')) close()
  })
  menu?.addEventListener('keydown', event => {
    const items = buttons(); const index = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'ArrowDown' ? (index + 1) % items.length : event.key === 'ArrowUp' ? (index - 1 + items.length) % items.length : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : -1
    if (next >= 0 && items.length) { event.preventDefault(); items[next]?.focus() }
    if (event.key === 'Tab') close(true)
  })
  document.addEventListener('click', event => { if (toggle.isConnected && !menu?.contains(event.target as Node)) close() })
  window.addEventListener('resize', () => { if (toggle.isConnected) close() })
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape' && toggle.isConnected && root.classList.contains('more-actions-open')) { event.preventDefault(); close(true) }
  })
  return { close }
}
