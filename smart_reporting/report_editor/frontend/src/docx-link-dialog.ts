import { buttonClasses } from './button'
import { createModal } from './modal'

/** 仅负责链接设置界面，来源选区与 URL 校验仍由调用方的原生写回协议处理。 */
export function openDocxLinkDialog(root: HTMLElement, initialHref: string, options: {
  unavailable(): boolean
  apply(href: string): void
  onClose(): void
}) {
  let disposed = false
  const close = () => {
    if (disposed) return
    dispose()
    options.onClose()
  }
  const modal = createModal({ root, label: 'Link', cardClass: 'docx-settings-dialog docx-link-dialog', closeLabel: '关闭超链接', onRequestClose: close, content: `
    <header><h2>超链接</h2></header><form><div class="docx-link-body">
      <label>链接地址<input aria-label="Link URL" type="text" autocomplete="url" spellcheck="false"></label>
      <p role="alert" aria-live="polite" aria-label="超链接错误" tabindex="0"></p>
      </div><footer>
      <button type="button" data-action="cancel" data-command="cancelLink" class="${buttonClasses('secondary')}">取消</button>
      <button type="submit" data-command="applyLink" class="${buttonClasses('primary')}">应用</button>
      </footer></form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  const apply = modal.card.querySelector<HTMLButtonElement>('[type=submit]')!
  const error = modal.card.querySelector<HTMLElement>('[role=alert]')!
  input.value = initialHref
  const refresh = () => { input.disabled = apply.disabled = options.unavailable() }
  function dispose() {
    if (disposed) return
    disposed = true
    modal.remove()
  }
  modal.card.querySelector('[data-command=cancelLink]')!.addEventListener('click', close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    if (disposed) return
    try {
      if (options.unavailable()) throw new Error('当前文档不可编辑或正在保存')
      options.apply(input.value)
      close()
    } catch (cause) {
      error.textContent = cause instanceof Error ? cause.message : String(cause)
      error.scrollIntoView?.({ block: 'nearest' })
      refresh()
    }
  })
  refresh()
  modal.open(input.disabled ? modal.closeButton : input)
  return { refresh, dispose }
}
