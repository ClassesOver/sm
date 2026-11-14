import { createElement, X } from 'lucide'

import { installFocusTrap } from './focus-trap'
import { buttonClasses } from './button'

interface ModalOptions {
  root: HTMLElement
  content: string
  overlayClass?: string
  cardClass?: string
  closeClass?: string
  closeLabel?: string
  role?: 'dialog' | 'alertdialog'
  labelledBy?: string
  label?: string
  variant?: 'default' | 'wide' | 'warning' | 'media'
  onRequestClose?: () => void
}

const openModals: { overlay: HTMLElement; opener: HTMLElement | null }[] = []
const topModal = () => openModals.findLast(({ overlay }) => overlay.isConnected && !overlay.hidden)
const syncModalAccess = () => {
  const top = topModal()
  for (const modal of openModals) {
    modal.overlay.inert = modal !== top && !modal.overlay.contains(top?.overlay ?? null)
    modal.overlay.setAttribute('aria-modal', String(modal === top))
  }
}

export function createModal(options: ModalOptions) {
  const overlay = document.createElement('div')
  overlay.className = ['modal-overlay', options.overlayClass].filter(Boolean).join(' ')
  overlay.hidden = true
  overlay.setAttribute('role', options.role ?? 'dialog')
  overlay.setAttribute('aria-modal', 'true')
  if (options.labelledBy) overlay.setAttribute('aria-labelledby', options.labelledBy)
  if (options.label) overlay.setAttribute('aria-label', options.label)

  const card = document.createElement('section')
  card.className = [
    'modal-card',
    `modal-card--${options.variant ?? 'default'}`,
    options.cardClass,
  ].filter(Boolean).join(' ')
  card.innerHTML = options.content
  overlay.append(card)

  const closeButton = options.closeLabel
    ? document.createElement('button')
    : null
  if (closeButton) {
    closeButton.type = 'button'
    closeButton.className = ['modal-close', buttonClasses('quiet', true), options.closeClass].filter(Boolean).join(' ')
    closeButton.setAttribute('aria-label', options.closeLabel!)
    closeButton.title = options.closeLabel!
    closeButton.append(createElement(X, { width: 18, height: 18, 'aria-hidden': 'true' }))
    card.prepend(closeButton)
  }

  options.root.append(overlay)
  const uninstallFocusTrap = installFocusTrap(overlay)
  const entry = { overlay, opener: null as HTMLElement | null }

  const restoreFocus = () => {
    if (entry.opener?.isConnected) entry.opener.focus()
    entry.opener = null
  }
  const deactivate = () => {
    const wasTop = topModal() === entry
    for (const modal of openModals) {
      if (modal !== entry && modal.opener && overlay.contains(modal.opener)) modal.opener = entry.opener
    }
    const index = openModals.indexOf(entry)
    if (index !== -1) openModals.splice(index, 1)
    overlay.inert = false
    syncModalAccess()
    return wasTop
  }
  const close = () => {
    const wasTop = deactivate()
    overlay.hidden = true
    if (wasTop) restoreFocus()
    else entry.opener = null
  }
  const remove = () => {
    const wasTop = deactivate()
    overlay.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keydown', onKeyDown)
    uninstallFocusTrap()
    overlay.remove()
    if (wasTop) restoreFocus()
    else entry.opener = null
  }
  const requestClose = () => {
    if (topModal() !== entry) return
    if (options.onRequestClose) options.onRequestClose()
    else close()
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
    if (event.target instanceof Element && event.target.closest('dialog[open]')) return
    if (event.key === 'Escape' && topModal() === entry) {
      event.preventDefault()
      event.stopImmediatePropagation()
      requestClose()
    }
  }
  overlay.addEventListener('keydown', onKeyDown)
  window.addEventListener('keydown', onKeyDown)
  closeButton?.addEventListener('click', requestClose)
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) requestClose()
  })

  return {
    overlay,
    card,
    closeButton,
    close,
    remove,
    open(initialFocus?: HTMLElement | null) {
      if (overlay.hidden) {
        entry.opener = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
          ? document.activeElement
          : null
      }
      const index = openModals.indexOf(entry)
      if (index !== -1) openModals.splice(index, 1)
      openModals.push(entry)
      overlay.parentElement?.append(overlay)
      overlay.hidden = false
      syncModalAccess()
      ;(initialFocus ?? closeButton ?? card.querySelector<HTMLElement>('button, input, select, textarea, a[href]'))?.focus()
    },
  }
}
