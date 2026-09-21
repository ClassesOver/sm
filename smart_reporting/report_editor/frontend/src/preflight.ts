import { createModal } from './modal'

export interface PreflightWarning { code: string; label: string; target?: string }
export function reportPreflight(markdown: string, editor: HTMLElement): PreflightWarning[] {
  const warnings: PreflightWarning[] = []
  if (!markdown.trim()) warnings.push({ code: 'empty', label: '报告内容为空' })
  if (!/^#{1,6}\s+\S/m.test(markdown)) warnings.push({ code: 'heading', label: '尚未创建章节标题', target: '.editor-surface' })
  const emptyHeadings = markdown.split('\n').filter((line) => /^#{1,6}\s*$/.test(line)).length
  if (emptyHeadings) warnings.push({ code: 'empty-heading', label: `${emptyHeadings} 个章节标题为空`, target: 'h1, h2, h3, h4, h5, h6' })
  const missingAlt = Array.from(editor.querySelectorAll<HTMLImageElement>('img')).filter(
    (image) => !image.alt.trim(),
  ).length
  if (missingAlt) warnings.push({ code: 'image-alt', label: `${missingAlt} 张图片缺少说明`, target: 'img:not([alt]), img[alt=""]' })
  return warnings
}

export function showPreflightPanel(root: HTMLElement, warnings: PreflightWarning[], onContinue: (proceed: boolean) => void) {
  let closePanel: () => void = () => {}
  const modal = createModal({
    root,
    overlayClass: 'preflight-panel',
    cardClass: 'preflight-card',
    closeLabel: '关闭导出检查',
    labelledBy: 'preflight-title',
    onRequestClose: () => closePanel(),
    content: `<h2 id="preflight-title">导出前提示</h2><p>发现以下问题，建议先处理；也可以继续导出。</p><ul>${warnings.map((warning) => `<li><button type="button" class="ui-button ui-button--quiet" data-preflight-target="${warning.target ?? ''}">${warning.label}</button></li>`).join('')}</ul><div class="preflight-actions"><button type="button" class="ui-button ui-button--secondary" data-preflight="cancel">返回编辑</button><button type="button" class="ui-button ui-button--primary" data-preflight="continue">仍然导出</button></div>`,
  })
  const panel = modal.overlay
  modal.closeButton!.dataset.preflight = 'close'
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const close = (proceed: boolean) => {
    modal.remove()
    opener?.focus()
    onContinue(proceed)
  }
  closePanel = () => close(false)
  modal.open(modal.closeButton)
  panel.querySelectorAll<HTMLButtonElement>('[data-preflight="close"], [data-preflight="cancel"]').forEach((button) => button.addEventListener('click', () => close(false)))
  panel.querySelector<HTMLButtonElement>('[data-preflight="continue"]')!.addEventListener('click', () => close(true))
  panel.querySelectorAll<HTMLButtonElement>('[data-preflight-target]').forEach((button) => button.addEventListener('click', () => {
    const target = button.dataset.preflightTarget ? root.querySelector<HTMLElement>(button.dataset.preflightTarget) : null
    target?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    target?.focus?.({ preventScroll: true })
  }))
  return panel
}
