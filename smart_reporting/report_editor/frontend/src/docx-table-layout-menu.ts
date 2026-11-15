import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { DocxTableCommands } from './docx-tables'
import { TABLE_AUTO_FIT_OPTIONS } from './docx-table-properties-source'
import { IconAutoFit, IconCaret, IconColDelete, IconDeleteCells, IconRowDelete, IconSelectCells, IconTableDelete } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { installPopoverDismiss } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'

// Keep the web ribbon's Chinese labels for the three upstream modes.
const autoFitLabels = {
  ribbonAutoFitContents: '根据内容自动调整',
  ribbonAutoFitWindow: '根据窗口自动调整',
  ribbonFixedColumnWidth: '固定列宽',
}

// GenOffice Ribbon.tsx Table Layout menus.
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
  autofit: {
    label: '自动调整', icon: IconAutoFit, className: 'table-command-button table-autofit-button',
    items: TABLE_AUTO_FIT_OPTIONS.map(([mode, label]) => [`table-autofit-${mode}`, autoFitLabels[label], IconAutoFit] as const),
  },
} as const

export function createDocxTableLayoutMenu(
  type: keyof typeof menus,
  run: DocxTableCommands['run'] | undefined,
  reason: DocxTableCommands['reason'],
  active?: DocxTableCommands['active'],
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
  const currentMode = document.createElement('small')
  if (type === 'autofit') {
    const caption = trigger.querySelector('span')!
    const copy = document.createElement('span')
    copy.className = 'table-command-copy'
    caption.replaceWith(copy)
    copy.append(caption, currentMode)
  }
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
    button.setAttribute('role', type === 'autofit' ? 'menuitemradio' : 'menuitem')
    if (type === 'autofit') {
      const marker = document.createElement('span')
      marker.className = 'table-menu-state'
      marker.setAttribute('aria-hidden', 'true')
      button.append(marker)
    }
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
    let selectedLabel: string | undefined
    const reasons = items.map(({ button, action, label }) => {
      const unavailable = reason(action)
      update(button, label, unavailable)
      if (type === 'autofit') {
        const selected = active?.(action) ?? false
        button.setAttribute('aria-checked', String(selected))
        button.classList.toggle('active', selected)
        if (selected) selectedLabel = label
      }
      return unavailable
    })
    if (type === 'autofit') currentMode.textContent = selectedLabel ?? autoFitLabels.ribbonFixedColumnWidth
    update(trigger, definition.label, reasons.every(Boolean) ? reasons[0] ?? null : null)
    if (type === 'autofit' && !trigger.disabled) trigger.setAttribute('aria-description', currentMode.textContent ?? '')
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
    const selected = buttons.find(button => button.getAttribute('aria-checked') === 'true')
    const focusTarget = last ? buttons.at(-1) : selected ?? buttons[0]
    focusTarget?.focus({ preventScroll: true })
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
