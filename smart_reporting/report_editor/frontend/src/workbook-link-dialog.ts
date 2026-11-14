// 固定源 f8c17004 apps/sheets/src/renderer/ExcelShell.tsx LinkDialog（Insert ▸ 链接）：地址输入，已有链接时显示“删除链接”，
// 空地址时“确定”不可用，Enter 提交。文案取固定源 i18n/app/zh.ts；地址规范化 normalizeLinkTarget 逐字照搬 univer-sync.ts。
import { createModal } from './modal'

/// Normalizes dialog input into the wire target format: '#Sheet!A1' for
/// internal anchors, a full URL otherwise. Bare domains get https://.
export function normalizeLinkTarget(input: string): string | null {
  const trimmed = input.trim()
  if (trimmed.length === 0 || trimmed.length > 2083) return null
  if (/^(https?:\/\/|mailto:)/i.test(trimmed)) return trimmed
  if (/^#?'?[^'!]+'?!\$?[A-Za-z]{1,3}\$?[0-9]+$/.test(trimmed)) {
    return trimmed.startsWith('#') ? trimmed : `#${trimmed}`
  }
  if (/^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(trimmed)) return `https://${trimmed}`
  return null
}

export const LINK_TEXT = {
  insertTitle: '插入链接', editTitle: '编辑链接',
  addressLabel: '地址——网页（https://…）或工作表引用（Sheet1!A1）', placeholder: '如 https://example.com 或 Sheet1!A1',
  remove: '删除链接', invalid: '请输入网址（https://…）或工作表引用（如 Sheet1!A1）。',
  saved: '链接已保存——点击单元格即可打开。', removed: '链接已删除。',
} as const

export function createWorkbookLinkDialog(root: HTMLElement, apply: (target: string | null) => Promise<void>) {
  let disposed = false, busy = false
  const modal = createModal({ root, label: LINK_TEXT.insertTitle, closeLabel: '关闭链接', overlayClass: 'workbook-ribbon-format-overlay',
    cardClass: 'workbook-ribbon-format-dialog workbook-link-dialog', content: `
    <h2 data-link-title>${LINK_TEXT.insertTitle}</h2>
    <label class="workbook-link-field">${LINK_TEXT.addressLabel}<input type="text" data-link-address autocomplete="off" spellcheck="false" placeholder="${LINK_TEXT.placeholder}"></label>
    <p class="workbook-ribbon-format-error" role="alert"></p>
    <div class="workbook-ribbon-format-actions"><button type="button" data-link-remove hidden>${LINK_TEXT.remove}</button><button type="button" data-link-cancel>取消</button><button type="button" class="primary" data-link-ok disabled>确定</button></div>` })
  const title = modal.card.querySelector<HTMLElement>('[data-link-title]')!, input = modal.card.querySelector<HTMLInputElement>('[data-link-address]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!, ok = modal.card.querySelector<HTMLButtonElement>('[data-link-ok]')!
  const remove = modal.card.querySelector<HTMLButtonElement>('[data-link-remove]')!
  const run = async (target: string | null) => {
    if (disposed || busy) return
    busy = true; ok.disabled = remove.disabled = true; error.textContent = ''
    try { await apply(target); modal.close() }
    catch (cause) { error.textContent = (cause as Error).message }
    finally { busy = false; remove.disabled = false; ok.disabled = !input.value.trim() }
  }
  const submit = () => {
    if (!input.value.trim()) return
    const target = normalizeLinkTarget(input.value)
    if (target === null) { error.textContent = LINK_TEXT.invalid; return }
    void run(target)
  }
  input.addEventListener('input', () => { ok.disabled = !input.value.trim(); error.textContent = '' })
  input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); submit() } })
  ok.addEventListener('click', submit)
  remove.addEventListener('click', () => void run(null))
  modal.card.querySelector('[data-link-cancel]')!.addEventListener('click', modal.close)
  return {
    open(current: string | null) {
      if (disposed) return
      const label = current === null ? LINK_TEXT.insertTitle : LINK_TEXT.editTitle
      title.textContent = label; modal.card.closest('[role="dialog"]')?.setAttribute('aria-label', label)
      input.value = current ?? ''; remove.hidden = current === null; ok.disabled = !input.value.trim(); error.textContent = ''
      modal.open(input)
    },
    close() { modal.close() },
    dispose() { disposed = true; modal.remove() },
  }
}
