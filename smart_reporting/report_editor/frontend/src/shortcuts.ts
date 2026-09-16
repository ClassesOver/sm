import { installFocusTrap } from './focus-trap'

export function createShortcutsPanel() {
  const dialog = document.createElement('div')
  dialog.className = 'shortcuts-panel'
  dialog.hidden = true
  dialog.innerHTML = `<section class="shortcuts-card" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title"><button type="button" class="shortcuts-close" aria-label="关闭快捷键帮助">×</button><h2 id="shortcuts-title">快捷键</h2><dl><div><dt>搜索和替换</dt><dd>Ctrl / ⌘ + F</dd></div><div><dt>保存</dt><dd>Ctrl / ⌘ + S</dd></div><div><dt>导出 PDF</dt><dd>Ctrl / ⌘ + Shift + E</dd></div><div><dt>专注模式</dt><dd>Ctrl / ⌘ + Shift + F</dd></div><div><dt>退出弹窗或专注模式</dt><dd>Esc</dd></div></dl></section>`
  document.body.append(dialog)
  installFocusTrap(dialog)
  const close = dialog.querySelector<HTMLButtonElement>('.shortcuts-close')!
  let opener: HTMLElement | null = null
  const hide = () => { dialog.hidden = true; opener?.focus(); opener = null }
  close.addEventListener('click', hide)
  dialog.addEventListener('click', (event) => { if (event.target === dialog) hide() })
  window.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !dialog.hidden) hide() })
  return { dialog, close, open: () => { opener = document.activeElement instanceof HTMLElement ? document.activeElement : null; dialog.hidden = false; close.focus() } }
}
