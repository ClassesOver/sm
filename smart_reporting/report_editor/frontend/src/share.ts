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
    content: `<h2 id="share-title">分享编辑链接</h2>
      <p class="share-warning" role="note">获得链接的人可以编辑此修订版。请只发送给信任的人，链接 30 天后自动失效。</p>
      <button type="button" class="ui-button ui-button--primary" data-share="create">生成并复制链接</button>
      <div class="share-link" hidden>
        <div class="share-link-row">
          <input data-share="url" aria-label="分享编辑链接" readonly>
          <button type="button" class="ui-button ui-button--secondary" data-share="copy">复制链接</button>
        </div>
        <span class="share-link-meta" data-share="expires"></span>
        <p class="share-renew-note" data-share="renew-note" hidden>旧链接仍有效，直到各自到期。</p>
      </div>
      <p class="share-status" data-share="status" role="status" aria-live="polite"></p>`,
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
