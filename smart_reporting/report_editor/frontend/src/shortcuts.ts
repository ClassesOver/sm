import { createModal } from './modal'

export function createShortcutsPanel() {
  const modal = createModal({
    root: document.body,
    overlayClass: 'shortcuts-panel',
    cardClass: 'shortcuts-card',
    closeClass: 'shortcuts-close',
    closeLabel: '关闭快捷键帮助',
    labelledBy: 'shortcuts-title',
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--violet" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="6" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M9 18h6"/></svg>
        </span>
        <div>
          <h2 id="shortcuts-title">快捷键</h2>
          <p class="panel-subtitle">不用鼠标也能高效编辑</p>
        </div>
      </div>
      <dl><div><dt>搜索和替换</dt><dd>Ctrl / ⌘ + F</dd></div><div><dt>保存</dt><dd>Ctrl / ⌘ + S</dd></div><div><dt>导出 PDF</dt><dd>Ctrl / ⌘ + Shift + E</dd></div><div><dt>专注模式</dt><dd>Ctrl / ⌘ + Shift + F</dd></div><div><dt>退出弹窗或专注模式</dt><dd>Esc</dd></div></dl>`,
  })
  return { dialog: modal.overlay, close: modal.closeButton!, open: () => modal.open(modal.closeButton) }
}
