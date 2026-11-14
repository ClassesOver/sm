import { buttonClasses } from './button'
import { installFocusTrap } from './focus-trap'

/** 便签及待保存绘图的窗口外观；提交、过期引用和移除仍由宿主管理。 */
export function showPdfObjectDialog(dialog: HTMLDialogElement, initialFocus: HTMLElement) {
  const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const title = dialog.getAttribute('aria-label') ?? '编辑对象'
  const heading = document.createElement('header'), label = document.createElement('h2'), close = document.createElement('button')
  heading.className = 'pdf-object-dialog-heading'; label.textContent = title
  close.type = 'button'; close.className = 'pdf-object-dialog-close ' + buttonClasses('quiet', true)
  close.dataset.pdfObjectClose = ''; close.setAttribute('aria-label', `关闭${title}`); close.textContent = '×'
  close.addEventListener('click', () => dialog.close())
  heading.append(label, close); dialog.prepend(heading); dialog.classList.add('pdf-object-dialog')
  const release = installFocusTrap(dialog)
  const preserveComposition = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && event.isComposing) event.preventDefault()
  }
  dialog.addEventListener('keydown', preserveComposition)
  dialog.addEventListener('close', () => {
    release()
    dialog.removeEventListener('keydown', preserveComposition)
    // 替换窗口的旧close可能晚于新窗口showModal，不能将焦点移出新窗口。
    if (previous?.isConnected && !dialog.ownerDocument.querySelector('dialog[open]')) previous.focus({ preventScroll: true })
  }, { once: true })
  dialog.addEventListener('cancel', event => { event.preventDefault(); dialog.close() })
  dialog.showModal(); initialFocus.focus()
}
