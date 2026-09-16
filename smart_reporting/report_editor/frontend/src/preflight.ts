import { installFocusTrap } from './focus-trap'

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
  const panel = document.createElement('section')
  panel.className = 'preflight-panel'
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-modal', 'true')
  panel.innerHTML = `<div class="preflight-card"><button type="button" data-preflight="close" aria-label="关闭导出检查">×</button><h2>导出前提示</h2><p>发现以下问题，建议先处理；也可以继续导出。</p><ul>${warnings.map((warning) => `<li><button type="button" data-preflight-target="${warning.target ?? ''}">${warning.label}</button></li>`).join('')}</ul><div class="preflight-actions"><button type="button" data-preflight="cancel">返回编辑</button><button type="button" data-preflight="continue">仍然导出</button></div></div>`
  root.append(panel)
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const uninstallFocusTrap = installFocusTrap(panel)
  const close = (proceed: boolean) => {
    window.removeEventListener('keydown', onKeyDown)
    uninstallFocusTrap()
    panel.remove()
    opener?.focus()
    onContinue(proceed)
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') close(false)
  }
  window.addEventListener('keydown', onKeyDown)
  panel.querySelector<HTMLButtonElement>('[data-preflight="close"]')?.focus()
  panel.querySelectorAll<HTMLButtonElement>('[data-preflight="close"], [data-preflight="cancel"]').forEach((button) => button.addEventListener('click', () => close(false)))
  panel.querySelector<HTMLButtonElement>('[data-preflight="continue"]')!.addEventListener('click', () => close(true))
  panel.querySelectorAll<HTMLButtonElement>('[data-preflight-target]').forEach((button) => button.addEventListener('click', () => {
    const target = button.dataset.preflightTarget ? root.querySelector<HTMLElement>(button.dataset.preflightTarget) : null
    target?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    target?.focus?.({ preventScroll: true })
  }))
  return panel
}
