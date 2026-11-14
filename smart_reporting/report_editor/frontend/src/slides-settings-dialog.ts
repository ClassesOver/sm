import { buttonClasses } from './button'
import { installFocusTrap } from './focus-trap'

/** 内联设置弹窗共用桌面关闭与焦点行为，不参与字段提交。 */
export function showSlidesSettingsDialog(dialog: HTMLDialogElement) {
  const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  dialog.classList.add('slides-settings-dialog')
  const close = document.createElement('button')
  close.type = 'button'; close.className = buttonClasses('quiet', true)
  close.dataset.settingsClose = ''; close.setAttribute('aria-label', `关闭${dialog.getAttribute('aria-label') ?? '设置'}`)
  close.textContent = '×'; close.addEventListener('click', () => dialog.close())
  dialog.prepend(close)
  const release = installFocusTrap(dialog)
  dialog.addEventListener('close', () => {
    release(); dialog.remove()
    if (previous?.isConnected) previous.focus({ preventScroll: true })
  }, { once: true })
  dialog.addEventListener('cancel', event => { event.preventDefault(); dialog.close() })
  dialog.showModal()
  dialog.querySelector<HTMLInputElement | HTMLSelectElement>('input, select')?.focus()
}
