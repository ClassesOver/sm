import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { createModal } from './modal'
import { FormatCellsDialog } from './vendor/genoffice-sheets-format/FormatCellsDialog'
import type { FormatCellsDraft } from './vendor/genoffice-sheets-format/format-cells'
import './workbook-format-cells.css'

/** The source dialog emits one validated batch, not sequential partial edits. */
export function createFormatCellsDialog(root: HTMLElement, options: {
  current(): { draft: FormatCellsDraft; anchor: number | string | null }
  apply(commands: string[]): Promise<void> | void
}) {
  let react: Root | undefined, busy = false, disposed = false
  const close = () => { if (!busy && !disposed) { react?.unmount(); react = undefined; modal.close() } }
  const modal = createModal({ root, label: '设置单元格格式', overlayClass: 'workbook-format-cells-overlay', cardClass: 'workbook-format-cells-host', content: '<div data-format-cells-mount></div>', onRequestClose: close })
  return {
    open() {
      if (disposed || busy) return
      const current = options.current()
      react?.unmount()
      modal.open()
      react = createRoot(modal.card.querySelector('[data-format-cells-mount]')!)
      flushSync(() => react!.render(createElement(FormatCellsDialog, {
        selectionFormat: null, initialDraft: current.draft, anchorValue: current.anchor,
        onApply: async commands => { busy = true; try { await options.apply(commands) } finally { busy = false } }, onClose: close,
      })))
      modal.card.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus()
    },
    dispose() { disposed = true; react?.unmount(); react = undefined; modal.remove() },
  }
}
