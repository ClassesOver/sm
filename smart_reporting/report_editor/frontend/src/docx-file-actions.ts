import { createModal } from './modal'
import { buttonClasses } from './button'
import type { createNativeApi, NativeWordFileResult } from './native-api'

export type DocxFileAction = 'new' | 'save-as'
const savedOnly = '另存为仅复制已保存的修订；请先保存或撤销当前修改，再另存为。'

function createdDocumentUrl(result: NativeWordFileResult): string {
  const raw = result?.editor?.openUrl
  if (typeof result?.documentId !== 'string' || !result.documentId || !Number.isSafeInteger(result.revision) || result.revision < 1 || typeof raw !== 'string' || !raw || raw !== raw.trim()) throw new Error('新文档地址无效，请重试')
  let url: URL
  try { url = new URL(raw, location.origin) } catch { throw new Error('新文档地址无效，请重试') }
  if (url.origin !== location.origin || url.username || url.password || url.search || url.hash || !/^\/reports\/v1\/native\/open\/[A-Za-z0-9._~=-]+$/.test(url.pathname)) throw new Error('新文档地址校验失败，请重试')
  return url.href
}

/** Creates a separate server document from the saved source; never rewrites the live editor. */
export function createDocxFileActions(options: {
  root: HTMLElement
  api: Pick<ReturnType<typeof createNativeApi>, 'newWord' | 'saveWordAs'>
  sourceSha256: string
  displayName?: string | null
  blocked(): string | null
  pendingEdits(): boolean
  flush(): void
  onError(error: unknown): void
  navigate?(url: string): void
}) {
  let disposed = false, busy = false, generation = 0, kind: DocxFileAction = 'new'
  const reason = (action: DocxFileAction): string | null => disposed ? 'Word 文件操作已关闭' : options.blocked() ?? (action === 'save-as' && options.pendingEdits() ? savedOnly : null)
  const report = (error: unknown) => {
    message.textContent = error instanceof Error ? error.message : String(error)
    options.onError(error)
  }
  const close = () => { generation++; busy = false; modal.close(); delivery.replaceChildren() }
  const modal = createModal({ root: options.root, label: 'Word 文件', closeLabel: '关闭文件操作', onRequestClose: close, content: `
    <h2></h2><form>
      <label>文件名<input name="filename" aria-label="文件名" maxlength="160" required autocomplete="off"></label>
      <p data-file-note></p><p role="alert"></p><div data-file-result aria-live="polite"></div>
      <button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button>
      <button type="submit" class="${buttonClasses('primary')}">创建</button>
    </form>` })
  const title = modal.card.querySelector('h2')!, note = modal.card.querySelector('[data-file-note]')!
  const input = modal.card.querySelector<HTMLInputElement>('input')!, submit = modal.card.querySelector<HTMLButtonElement>('[type=submit]')!
  const message = modal.card.querySelector<HTMLElement>('[role=alert]')!, delivery = modal.card.querySelector<HTMLElement>('[data-file-result]')!
  const resetBusy = () => { input.disabled = false; submit.disabled = false }
  modal.card.querySelector('[data-action=cancel]')!.addEventListener('click', close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    if (disposed || busy || modal.overlay.hidden || submit.disabled) return
    const requestGeneration = generation, action = kind
    const current = () => !disposed && generation === requestGeneration && !modal.overlay.hidden
    void (async () => {
      try {
        const blocked = reason(action); if (blocked) throw new Error(blocked)
        options.flush()
        const afterFlush = reason(action); if (afterFlush) throw new Error(afterFlush)
        let filename = input.value.trim()
        if (!filename || /[\\/:*?"<>|\u0000-\u001f\u007f]/.test(filename) || filename.startsWith('.')) throw new Error('请输入有效文件名，不得包含路径、保留符号或控制字符')
        if (!/\.docx$/i.test(filename)) filename += '.docx'
        if (Array.from(filename).length > 160) throw new Error('文件名（含 .docx 扩展名）不能超过 160 个字符')
        busy = true; input.disabled = true; submit.disabled = true; message.textContent = ''; delivery.replaceChildren()
        const payload = { requestId: crypto.randomUUID(), expectedSha256: options.sourceSha256, filename }
        const result = await (action === 'new' ? options.api.newWord(payload) : options.api.saveWordAs(payload))
        if (!current()) return
        const blockedAfter = reason(action); if (blockedAfter) throw new Error(blockedAfter)
        const url = createdDocumentUrl(result), link = document.createElement('a')
        link.href = url; link.textContent = '打开新文档'; link.target = '_blank'; link.rel = 'noopener'
        link.addEventListener('click', event => {
          if (!current()) { event.preventDefault(); return }
          const blocked = reason(action)
          if (blocked) { event.preventDefault(); report(new Error(blocked)); return }
          if (options.navigate) { event.preventDefault(); options.navigate(url) }
        })
        delivery.append(link)
        message.textContent = '新文档已创建；当前文档保持打开。'
      } catch (error) {
        if (!current()) return
        resetBusy(); report(error)
      } finally { if (current()) busy = false }
    })()
  })
  return {
    reason,
    open(action: DocxFileAction) {
      if (disposed) return
      const blocked = reason(action)
      if (blocked) { options.onError(new Error(blocked)); return }
      generation++; busy = false; kind = action; resetBusy(); message.textContent = ''; delivery.replaceChildren()
      const name = options.displayName?.replace(/\.docx$/i, '') || '文档'
      input.value = action === 'new' ? '新建文档.docx' : `${name} - 副本.docx`
      title.textContent = action === 'new' ? '新建 Word 文档' : '另存为 Word 文档'
      modal.overlay.setAttribute('aria-label', title.textContent)
      note.textContent = action === 'new' ? '创建独立的空白文档；当前文档及未保存的修改保持不变。' : savedOnly
      submit.textContent = action === 'new' ? '新建' : '另存为'
      modal.open(input); input.select()
    },
    dispose() { if (disposed) return; disposed = true; generation++; modal.remove() },
  }
}
