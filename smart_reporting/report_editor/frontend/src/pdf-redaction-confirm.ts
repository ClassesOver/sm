import { buttonClasses } from './button'
import { installFocusTrap } from './focus-trap'

export function bindPdfRedactionConfirm(root: HTMLElement) {
  const owner = root.ownerDocument
  const dialog = owner.createElement('dialog')
  dialog.className = 'pdf-layout-dialog'
  dialog.setAttribute('aria-label', '确认应用涂黑')
  dialog.setAttribute('aria-describedby', 'pdf-redaction-confirm-description')
  const title = owner.createElement('h3')
  title.textContent = '确认应用涂黑'
  const message = owner.createElement('p')
  message.id = 'pdf-redaction-confirm-description'
  const actions = owner.createElement('div')
  actions.className = 'pdf-layout-actions'
  const cancel = owner.createElement('button'), confirm = owner.createElement('button')
  cancel.type = confirm.type = 'button'
  cancel.className = buttonClasses('secondary'); confirm.className = buttonClasses('danger')
  cancel.textContent = '取消'; confirm.textContent = '应用到新修订'
  cancel.dataset.pdfRedactionCancel = ''; confirm.dataset.pdfRedactionConfirm = ''
  actions.append(cancel, confirm); dialog.append(title, message, actions); root.append(dialog)
  const releaseFocusTrap = installFocusTrap(dialog)
  let resolve: ((accepted: boolean) => void) | undefined
  let opener: HTMLElement | null = null, disposed = false
  function finish(accepted: boolean) {
    const notify = resolve
    if (!notify) return
    resolve = undefined
    if (dialog.open) dialog.close()
    if (opener?.isConnected && !opener.matches(':disabled')) opener.focus({preventScroll:true})
    opener = null
    notify(accepted)
  }
  confirm.addEventListener('click', () => finish(true))
  cancel.addEventListener('click', () => finish(false))
  dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false) })
  dialog.addEventListener('close', () => finish(false))
  return {
    async open(count: number) {
      if (disposed || resolve) return false
      message.textContent = '新修订中 ' + count + ' 个标记区域的内容将被永久移除。原修订会保留。'
      opener = owner.activeElement instanceof HTMLElement ? owner.activeElement : null
      dialog.showModal()
      cancel.focus()
      return new Promise<boolean>(done => { resolve = done })
    },
    dispose() {
      if (disposed) return
      disposed = true; finish(false); releaseFocusTrap(); dialog.remove()
    },
  }
}
