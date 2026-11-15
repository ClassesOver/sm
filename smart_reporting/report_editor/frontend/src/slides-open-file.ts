import { buttonClasses } from './button'
import { createdDocumentUrl } from './docx-file-actions'
import { createModal } from './modal'
import type { createNativeApi } from './native-api'

export function createSlidesOpenFile(root: HTMLElement, upload: ReturnType<typeof createNativeApi>['openSlidesFile']) {
  const modal = createModal({
    root, label: '打开演示文稿', closeLabel: '关闭文件选择', onRequestClose: close,
    content: '<h2>打开演示文稿</h2><label>选择 PPTX 文件<input type="file" accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"></label><p role="status"></p><div aria-live="polite"></div>',
  })
  const picker = modal.card.querySelector('input')!
  const status = modal.card.querySelector<HTMLElement>('[role="status"]')!
  const result = modal.card.querySelector<HTMLElement>('[aria-live]')!
  let pending: AbortController | undefined
  let request: { file: File; id: string } | undefined

  async function run(file: File) {
    if (pending) return
    if (!/\.pptx$/i.test(file.name) || file.size < 1 || file.size > 24 * 1024 * 1024) {
      status.textContent = '请选择 1 字节至 24 MiB 的 PPTX 文件。'
      return
    }
    if (request?.file !== file) request = { file, id: crypto.randomUUID() }
    const controller = new AbortController()
    pending = controller
    picker.disabled = true
    status.textContent = '正在打开演示文稿…'
    result.replaceChildren()
    try {
      const opened = await upload(file, request.id, controller.signal)
      if (controller.signal.aborted) return
      const link = document.createElement('a')
      link.href = createdDocumentUrl(opened)
      link.target = '_blank'; link.rel = 'noopener'
      link.textContent = '打开演示文稿'
      result.append(link)
      status.textContent = opened.filename
      link.focus()
    } catch (error) {
      if (controller.signal.aborted) return
      status.textContent = error instanceof Error ? error.message : '文件无法打开。'
      const retry = document.createElement('button')
      retry.type = 'button'; retry.className = buttonClasses('secondary'); retry.textContent = '重试'
      retry.onclick = () => { void run(file) }
      result.append(retry)
    } finally {
      if (pending === controller) { pending = undefined; picker.disabled = false }
    }
  }

  picker.addEventListener('change', () => { const file = picker.files?.[0]; if (file) void run(file) })
  function close() {
    pending?.abort(); pending = undefined; request = undefined
    picker.disabled = false; picker.value = ''; status.textContent = ''; result.replaceChildren()
    modal.close()
  }
  return { open: () => { if (!modal.overlay.hidden) return; modal.open(picker); picker.click() },
    dispose() { close(); modal.remove() } }
}
