import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { DocxTableCommands } from './docx-tables'
import { IconCaret, IconColDelete, IconDeleteCells, IconRowDelete, IconSelectCells, IconTableDelete } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { installPopoverDismiss } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'

// GenOffice Ribbon.tsx TABLE_SELECT_ITEMS and the adjacent Table Layout Delete menu.
const menus = {
  select: {
    label: zh.ribbonSelect, icon: IconSelectCells, className: 'table-command-row table-command-row-caret',
    items: [
      ['table-select-cell', zh.ribbonSelectCell, IconSelectCells],
      ['table-select-column', zh.ribbonSelectColumn, IconSelectCells],
      ['table-select-row', zh.ribbonSelectRow, IconSelectCells],
      ['table-select-all', zh.ribbonSelectTable, IconSelectCells],
    ],
  },
  delete: {
    label: zh.ribbonTableDeleteMenu, icon: IconTableDelete, className: 'table-command-button',
    items: [
      ['table-delete-cells', zh.ribbonDeleteCells, IconDeleteCells],
      ['table-delete-column', zh.ribbonDeleteColumn, IconColDelete],
      ['table-delete-row', zh.ribbonDeleteRow, IconRowDelete],
      ['table-delete', zh.ribbonDeleteTable, IconTableDelete],
    ],
  },
} as const

export function createDocxTableLayoutMenu(
  type: keyof typeof menus,
  run: DocxTableCommands['run'] | undefined,
  reason: DocxTableCommands['reason'],
) {
  const definition = menus[type]
  const root = document.createElement('div'), trigger = document.createElement('button'), panel = document.createElement('div')
  root.className = 'rb-split-wrap'
  root.dataset.docxTableLayoutMenu = type
  const iconButton = (button: HTMLButtonElement, label: string, icon: typeof IconCaret) => {
    button.type = 'button'
    button.innerHTML = renderToStaticMarkup(createElement(icon, { size: 17 }))
    const caption = document.createElement('span')
    caption.textContent = label
    button.append(caption)
  }
  iconButton(trigger, definition.label, definition.icon)
  trigger.insertAdjacentHTML('beforeend', renderToStaticMarkup(createElement(IconCaret, { size: 12 })))
  trigger.className = definition.className
  trigger.dataset.action = `table-${type}-menu`
  trigger.setAttribute('aria-haspopup', 'menu')
  trigger.setAttribute('aria-expanded', 'false')
  panel.hidden = true
  panel.dataset.rbPanel = ''
  panel.className = 'layout-menu table-autofit-menu'
  panel.setAttribute('role', 'menu')
  panel.setAttribute('aria-label', definition.label)
  root.append(trigger, panel)
  let dismiss: (() => void) | undefined
  const close = () => {
    dismiss?.()
    dismiss = undefined
    panel.hidden = true
    trigger.setAttribute('aria-expanded', 'false')
  }
  const items = definition.items.map(([action, label, icon]) => {
    const button = document.createElement('button')
    iconButton(button, label, icon)
    button.dataset.action = action
    button.dataset.sourceAction = action
    button.setAttribute('role', 'menuitem')
    button.tabIndex = -1
    button.onclick = () => { if (panel.hidden) return; close(); if (!reason(action)) run?.(action) }
    panel.append(button)
    return { button, action, label }
  })
  const update = (button: HTMLButtonElement, label: string, unavailable: string | null) => {
    button.disabled = unavailable !== null
    button.title = unavailable ?? label
    button.setAttribute('aria-label', unavailable ? `${label}，${unavailable}` : label)
    if (unavailable) button.setAttribute('aria-description', unavailable)
    else button.removeAttribute('aria-description')
  }
  const refresh = () => {
    const reasons = items.map(({ button, action, label }) => {
      const unavailable = reason(action)
      update(button, label, unavailable)
      return unavailable
    })
    update(trigger, definition.label, reasons.every(Boolean) ? reasons[0] ?? null : null)
    if (trigger.disabled) close()
  }
  const available = () => items.map(({ button }) => button).filter(button => !button.disabled)
  const open = (last = false) => {
    refresh()
    if (trigger.disabled) return
    panel.hidden = false
    trigger.setAttribute('aria-expanded', 'true')
    dismiss = installPopoverDismiss(close, { inside: () => [root] })
    const buttons = available()
    buttons[last ? buttons.length - 1 : 0]?.focus({ preventScroll: true })
  }
  root.onmousedown = event => event.preventDefault()
  trigger.onclick = () => { if (panel.hidden) open(); else close() }
  root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget as Node | null)) close() })
  root.onkeydown = event => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return
    if (panel.hidden) {
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
      event.preventDefault()
      open(event.key === 'ArrowUp')
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
      trigger.focus()
      return
    }
    const buttons = available(), current = buttons.indexOf(document.activeElement as HTMLButtonElement)
    const offset = event.key === 'ArrowDown' ? current + 1 : event.key === 'ArrowUp' ? current - 1
      : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : null
    if (offset === null || !buttons.length) return
    event.preventDefault()
    buttons[(offset + buttons.length) % buttons.length].focus()
  }
  refresh()
  return { root, refresh, close }
}
