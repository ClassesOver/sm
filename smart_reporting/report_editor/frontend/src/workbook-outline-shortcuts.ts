// 固定源 global-shortcuts.ts / clear-selection-keyboard.ts 的 outline sheet gate。
import { hasWorkbookModal, isWorkbookGridKeyTarget } from './workbook-shortcut-target'

export function installOutlineShortcuts(host: HTMLElement, editable: () => boolean, cellEditing: () => boolean,
  command: (command: 'outline-group:auto' | 'outline-ungroup:auto') => void): { dispose(): void } {
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229 || !event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey
      || !['ArrowLeft', 'ArrowRight'].includes(event.code) || !editable() || cellEditing()) return
    if (!isWorkbookGridKeyTarget(event.target) || hasWorkbookModal(host.ownerDocument)) return
    event.preventDefault()
    command(event.code === 'ArrowRight' ? 'outline-group:auto' : 'outline-ungroup:auto')
  }
  window.addEventListener('keydown', onKeyDown)
  return { dispose() { window.removeEventListener('keydown', onKeyDown) } }
}
