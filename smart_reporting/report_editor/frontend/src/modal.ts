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
  let opener: HTMLElement | null = null

  const restoreFocus = () => {
    opener?.focus()
    opener = null
  }
  const close = () => {
    overlay.hidden = true
    restoreFocus()
  }
  const remove = () => {
    window.removeEventListener('keydown', onKeyDown)
    uninstallFocusTrap()
    overlay.remove()
    restoreFocus()
  }
  const requestClose = () => {
    if (options.onRequestClose) options.onRequestClose()
    else close()
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && !overlay.hidden) requestClose()
  }
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
      opener = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
        ? document.activeElement
        : null
      overlay.hidden = false
      ;(initialFocus ?? closeButton ?? card.querySelector<HTMLElement>('button, input, select, textarea, a[href]'))?.focus()
    },
  }
}
