import type { ShareResult } from './api'
import { copyText } from './clipboard'
import { createModal } from './modal'

const COPY_FEEDBACK_MS = 2000

type ShareStatusState = 'busy' | 'success' | 'error'

export function createSharePanel(root: HTMLElement, issue: () => Promise<ShareResult>) {
  const modal = createModal({
    root,
    closeLabel: '关闭分享',
    labelledBy: 'share-title',
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--share" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.59 13.51 6.83 3.98"/><path d="m15.41 6.51-6.82 3.98"/></svg>
        </span>
        <div>
          <h2 id="share-title">分享编辑链接</h2>
          <p class="panel-subtitle">获得链接的人可以编辑此修订版 · 链接 30 天后自动失效</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="share-link" hidden>
          <div class="share-link-row">
            <input data-share="url" aria-label="分享编辑链接" readonly>
            <button type="button" class="ui-button" data-share="copy">复制链接</button>
          </div>
          <div class="share-link-footer">
            <span class="share-link-meta" data-share="expires"></span>
            <span class="share-renew-note" data-share="renew-note" hidden>旧链接仍有效，直到各自到期。</span>
          </div>
        </div>
        <button type="button" class="ui-button ui-button--primary share-create" data-share="create">生成并复制链接</button>
        <p class="share-status" data-share="status" role="status" aria-live="polite"></p>
      </div>`,
  })
  const create = modal.overlay.querySelector<HTMLButtonElement>('[data-share="create"]')!
  const copy = modal.overlay.querySelector<HTMLButtonElement>('[data-share="copy"]')!
  const link = modal.overlay.querySelector<HTMLInputElement>('[data-share="url"]')!
  const linkBox = modal.overlay.querySelector<HTMLElement>('.share-link')!
  const renewNote = modal.overlay.querySelector<HTMLElement>('[data-share="renew-note"]')!
  const expiry = modal.overlay.querySelector<HTMLElement>('[data-share="expires"]')!
  const status = modal.overlay.querySelector<HTMLElement>('[data-share="status"]')!
  let copyFeedbackTimer: ReturnType<typeof setTimeout> | undefined

  const setStatus = (text: string, state?: ShareStatusState) => {
    status.textContent = text
    if (state) status.dataset.state = state
    else delete status.dataset.state
  }

  const copyLink = async () => {
    create.disabled = true
    copy.disabled = true
    try {
      await copyText(link.value)
      setStatus('链接已复制', 'success')
      clearTimeout(copyFeedbackTimer)
      copy.textContent = '已复制'
      copyFeedbackTimer = setTimeout(() => { copy.textContent = '复制链接' }, COPY_FEEDBACK_MS)
    } catch {
      setStatus('复制失败，请选中链接手动复制', 'error')
      if (!modal.overlay.hidden) {
        link.focus()
        link.select()
      }
    } finally {
      create.disabled = false
      copy.disabled = false
    }
  }
  copy.addEventListener('click', () => void copyLink())
  link.addEventListener('click', () => link.select())

  create.addEventListener('click', async () => {
    create.disabled = true
    copy.disabled = true
    setStatus('正在生成链接', 'busy')
    try {
      const result = await issue()
      link.value = result.openUrl
      linkBox.hidden = false
      expiry.textContent = `有效期至 ${new Date(result.expiresAt).toLocaleString('zh-CN')}`
      create.textContent = '再生成一条链接'
      renewNote.hidden = false
      if (!modal.overlay.hidden) await copyLink()
    } catch {
      setStatus('生成失败，请重试', 'error')
    } finally {
      create.disabled = false
      copy.disabled = false
    }
  })

  return {
    dialog: modal.overlay,
    close: modal.close,
    open() {
      clearTimeout(copyFeedbackTimer)
      copy.textContent = '复制链接'
      setStatus('')
      modal.open(linkBox.hidden ? create : copy)
    },
  }
}
