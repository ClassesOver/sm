import { createModal } from './modal'

export function createShortcutsPanel() {
  const modal = createModal({
    root: document.body,
    overlayClass: 'shortcuts-panel',
    cardClass: 'shortcuts-card',
    closeClass: 'shortcuts-close',
    closeLabel: '关闭快捷键帮助',
    labelledBy: 'shortcuts-title',
    content: `<h2 id="shortcuts-title">快捷键</h2><dl><div><dt>搜索和替换</dt><dd>Ctrl / ⌘ + F</dd></div><div><dt>保存</dt><dd>Ctrl / ⌘ + S</dd></div><div><dt>导出 PDF</dt><dd>Ctrl / ⌘ + Shift + E</dd></div><div><dt>专注模式</dt><dd>Ctrl / ⌘ + Shift + F</dd></div><div><dt>退出弹窗或专注模式</dt><dd>Esc</dd></div></dl>`,
  })
  return { dialog: modal.overlay, close: modal.closeButton!, open: () => modal.open(modal.closeButton) }
}
