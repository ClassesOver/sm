// 固定源 global-shortcuts.ts:87 的 Shift+F3 / grid gate，不触发原生 fx 会话。
import { hasWorkbookModal, isWorkbookGridKeyTarget } from './workbook-shortcut-target'

export function installFunctionShortcuts(host: HTMLElement, editable: () => boolean, open: () => void): { dispose(): void } {
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.isComposing || event.code !== 'F3' || !event.shiftKey || event.ctrlKey || event.metaKey || event.altKey
      || !editable() || !isWorkbookGridKeyTarget(event.target) || hasWorkbookModal(host.ownerDocument)) return
    event.preventDefault()
    open()
  }
  window.addEventListener('keydown', onKeyDown)
  return { dispose() { window.removeEventListener('keydown', onKeyDown) } }
}
