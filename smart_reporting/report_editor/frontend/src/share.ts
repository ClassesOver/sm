import type { ShareResult } from './api'
import { createModal } from './modal'

export function createSharePanel(root: HTMLElement, issue: () => Promise<ShareResult>) {
  const modal = createModal({
    root,
    closeLabel: '关闭分享',
    labelledBy: 'share-title',
    content: `<h2 id="share-title">分享编辑链接</h2>
      <p>获得链接的人可以编辑此修订版。链接有效期为 30 天。</p>
      <button type="button" class="ui-button ui-button--primary" data-share="create">生成并复制链接</button>
      <p data-share="renew-note" hidden>旧链接仍有效，直到各自到期。</p>
      <div class="share-link" hidden>
        <input data-share="url" aria-label="分享编辑链接" readonly>
        <button type="button" class="ui-button ui-button--secondary" data-share="copy">复制链接</button>
        <span data-share="expires"></span>
      </div>
      <p data-share="status" role="status" aria-live="polite"></p>`,
  })
  const create = modal.overlay.querySelector<HTMLButtonElement>('[data-share="create"]')!
  const copy = modal.overlay.querySelector<HTMLButtonElement>('[data-share="copy"]')!
  const link = modal.overlay.querySelector<HTMLInputElement>('[data-share="url"]')!
  const linkBox = modal.overlay.querySelector<HTMLElement>('.share-link')!
  const renewNote = modal.overlay.querySelector<HTMLElement>('[data-share="renew-note"]')!
  const expiry = modal.overlay.querySelector<HTMLElement>('[data-share="expires"]')!
  const status = modal.overlay.querySelector<HTMLElement>('[data-share="status"]')!

  const copyLink = async () => {
    create.disabled = true
    copy.disabled = true
    try {
      await navigator.clipboard.writeText(link.value)
      status.textContent = '链接已复制'
    } catch {
      status.textContent = '复制失败，请选中链接手动复制'
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

  create.addEventListener('click', async () => {
    create.disabled = true
    copy.disabled = true
    status.textContent = '正在生成链接'
    try {
      const result = await issue()
      link.value = result.openUrl
      linkBox.hidden = false
      expiry.textContent = `有效期至 ${new Date(result.expiresAt).toLocaleString('zh-CN')}`
      create.textContent = '再生成一条链接'
      renewNote.hidden = false
      if (!modal.overlay.hidden) await copyLink()
    } catch {
      status.textContent = '生成失败，请重试'
    } finally {
      create.disabled = false
      copy.disabled = false
    }
  })

  return {
    dialog: modal.overlay,
    close: modal.close,
    open() {
      status.textContent = ''
      modal.open(linkBox.hidden ? create : copy)
    },
  }
}
