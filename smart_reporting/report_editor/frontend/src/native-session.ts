import type { EditorShell } from './shell'
import type { NativeSaveRequest } from './native-draft'
import { NativeDraft } from './native-draft'
import type { NativeSaveResponse } from './native-api'

export interface NativeViewHandle {
  setSaving(saving: boolean): void
  refresh?(): Promise<void>
  dispose?(): void
  flushPendingEdits?(): void
  prepareSave?(): Promise<{confirmedPreviewDigest?: string}>
}
interface SessionOptions {
  draft: NativeDraft
  api: {
    save(payload: NativeSaveRequest): Promise<NativeSaveResponse>
    export(payload: NativeSaveRequest): Promise<NativeSaveResponse>
  }
  format: 'docx' | 'pdf'
  view: NativeViewHandle
  editingEnabled?: boolean
  refreshBusy?: () => boolean
  onStateChange?: () => void
  navigate?: (url: string) => void
}

export function bindNativeSession(shell: EditorShell, options: SessionOptions) {
  const { draft, api, view } = options
  const root = shell.editor.closest('.report-app') ?? shell.editor
  const delivery = document.createElement('section')
  delivery.className = 'native-delivery'
  delivery.setAttribute('aria-live', 'polite')
  delivery.hidden = true
  root.querySelector('.report-meta')?.insertAdjacentElement('afterend', delivery)
  const navigate = options.navigate ?? ((url: string) => window.location.assign(url))
  let preparing = false
  let savedFileSource: NativeSaveResponse | undefined
  const update = (showDraftStatus = true) => {
    for (const button of [shell.save, shell.exportPdf, shell.exportWord]) button.disabled = options.editingEnabled === false || preparing || draft.saving || draft.closed || options.refreshBusy?.() === true
    shell.status.setAttribute('aria-busy', String(preparing || draft.saving))
    options.onStateChange?.()
    if (draft.persistenceError) shell.statusLabel.textContent = draft.persistenceError
    else if (showDraftStatus && draft.dirty && !draft.saving) shell.statusLabel.textContent = '有未保存修改'
  }
  const renderResult = (result: NativeSaveResponse) => {
    delivery.replaceChildren()
    delivery.hidden = false
    const message = document.createElement('p')
    message.textContent = result.revisionRegistered
      ? `已保存修订 ${result.revision}；${result.validation.ok ? '验收通过' : '验收待复核或未通过'}`
      : '文件已保存，修订尚未登记；草稿已保留，可重试'
    delivery.append(message)
    for (const issue of result.validation.issues) {
      const item = document.createElement('p')
      item.textContent = issue.message || issue.code
      delivery.append(item)
    }
    for (const [format, artifact] of Object.entries(result.artifacts)) {
      if (!artifact?.downloadUrl) continue
      const url = safeUrl(artifact.downloadUrl)
      if (!url) continue
      const link = document.createElement('a')
      link.href = url
      link.textContent = format === 'word' ? '下载 Word' : '下载 PDF'
      link.referrerPolicy = 'no-referrer'
      delivery.append(link)
    }
  }
  let retryAction: 'save' | 'export' = 'save'
  const save = async (action: 'save' | 'export') => {
    if (options.editingEnabled === false || preparing || draft.saving || draft.closed || options.refreshBusy?.()) return
    retryAction = action
    shell.retry.hidden = true
    try {
      preparing = true
      update()
      view.flushPendingEdits?.()
      const snapshot = JSON.stringify(draft.operations)
      const confirmation = await view.prepareSave?.()
      if (snapshot !== JSON.stringify(draft.operations)) throw new Error('草稿已变化，请重新确认修改')
      const payload = draft.beginSave({ action, ...confirmation })
      view.setSaving(true)
      shell.statusLabel.textContent = action === 'export' ? '正在保存并导出' : '正在保存'
      const result = await api[action](payload)
      savedFileSource = result
      renderResult(result)
      draft.saveCompleted(result)
      shell.statusLabel.textContent = result.revisionRegistered ? `已保存修订 ${result.revision}` : '修订尚未登记，可重试'
      shell.retry.hidden = result.revisionRegistered
      const next = result.editor?.openUrl && safeUrl(result.editor.openUrl)
      if (result.revisionRegistered && next) {
        const open = document.createElement('a')
        open.className = 'native-next-revision'
        open.href = next
        open.textContent = '打开新修订继续编辑'
        open.addEventListener('click', event => { event.preventDefault(); navigate(next) })
        delivery.append(open)
      }
    } catch (error) {
      draft.saveFailed()
      shell.statusLabel.textContent = error instanceof Error ? error.message : '保存失败；草稿已保留'
      shell.retry.hidden = false
    } finally {
      preparing = false
      view.setSaving(false)
      // 已保存旧修订不能因解除“保存中”而再次进入编辑状态。
      update(false)
    }
  }
  const doSave = () => { void save('save') }
  const doExport = () => { void save('export') }
  const doRetry = () => { void save(retryAction) }
  const beforeLeave = (event: BeforeUnloadEvent) => {
    if (draft.dirty) { event.preventDefault(); event.returnValue = '' }
  }
  shell.save.addEventListener('click', doSave)
  shell.exportWord.addEventListener('click', doSave)
  shell.exportPdf.addEventListener('click', doExport)
  shell.retry.addEventListener('click', doRetry)
  window.addEventListener('beforeunload', beforeLeave)
  update()
  const flushForFileOperation = async (): Promise<NativeSaveResponse | undefined> => {
    if (draft.closed && savedFileSource?.revisionRegistered) return savedFileSource
    if (options.editingEnabled === false || preparing || draft.saving || draft.closed || options.refreshBusy?.()) throw new Error('当前文档只读或正在保存，请稍后重试')
    view.flushPendingEdits?.()
    if (!draft.dirty) return undefined
    savedFileSource = undefined
    await save('save')
    const saved = savedFileSource as NativeSaveResponse | undefined
    if (!saved) throw new Error(shell.statusLabel.textContent || '保存当前修改失败，未拆分文件')
    if (!saved.revisionRegistered) throw new Error('修订尚未登记；已生成文件下载保留，请完成登记后再拆分')
    return saved
  }
  return { save, update, flushForFileOperation, get preparing() { return preparing }, dispose() {
    shell.save.removeEventListener('click', doSave)
    shell.exportWord.removeEventListener('click', doSave)
    shell.exportPdf.removeEventListener('click', doExport)
    shell.retry.removeEventListener('click', doRetry)
    window.removeEventListener('beforeunload', beforeLeave)
    view.dispose?.()
  } }
}

function safeUrl(raw: string): string | undefined {
  try {
    const url = new URL(raw, window.location.origin)
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href
  } catch { /* 无效链接不成为可点击下载。 */ }
  return undefined
}
