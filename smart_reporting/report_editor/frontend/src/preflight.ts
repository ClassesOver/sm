import { createModal } from './modal'

export interface PreflightWarning { code: string; label: string; target?: string }
// 正式章节标题（h2-h4）由服务端编号映射锁定，导出时逐项核对级别、编号、标题与顺序。
/** 代码块（``` 或 ~~~ 围栏）之外的行；代码中的 `#` 注释不是章节标题。 */
function linesOutsideFences(markdown: string): string[] {
  const lines: string[] = []
  let fence: string | null = null
  for (const line of markdown.split('\n')) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1]?.[0]
    if (marker && (!fence || fence === marker)) {
      fence = fence ? null : marker
      continue
    }
    if (!fence) lines.push(line)
  }
  return lines
}

export function formalHeadings(markdown: string): string[] {
  const headings: string[] = []
  for (const line of linesOutsideFences(markdown)) {
    const heading = /^(#{2,4})\s+(.*?)\s*#*\s*$/.exec(line)
    if (heading) headings.push(`${heading[1].length}|${heading[2].trim()}`)
  }
  return headings
}

export function reportPreflight(
  markdown: string,
  editor: HTMLElement,
  expectedHeadings?: string[],
): PreflightWarning[] {
  const warnings: PreflightWarning[] = []
  if (expectedHeadings) {
    const actual = formalHeadings(markdown)
    if (actual.length !== expectedHeadings.length || actual.some((value, index) => value !== expectedHeadings[index])) {
      warnings.push({
        code: 'formal-headings',
        label: '正式章节标题或顺序已改变，导出校验将失败，请恢复原标题',
        target: 'h2, h3, h4',
      })
    }
  }
  if (!markdown.trim()) warnings.push({ code: 'empty', label: '报告内容为空' })
  const prose = linesOutsideFences(markdown)
  if (!prose.some((line) => /^#{1,6}\s+\S/.test(line))) warnings.push({ code: 'heading', label: '尚未创建章节标题', target: '.editor-surface' })
  const emptyHeadings = prose.filter((line) => /^#{1,6}\s*$/.test(line)).length
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
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--warning" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>
        </span>
        <div>
          <h2 id="preflight-title">导出前提示</h2>
          <p class="panel-subtitle">发现 ${warnings.length} 个问题，建议先处理；也可以继续导出。</p>
        </div>
      </div>
      <ul class="panel-body preflight-list">${warnings.map((warning, index) => `<li><button type="button" data-preflight-target="${index}"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg><span>${warning.label}</span></button></li>`).join('')}</ul>
      <div class="preflight-actions"><button type="button" class="ui-button ui-button--secondary" data-preflight="cancel">返回编辑</button><button type="button" class="ui-button ui-button--primary" data-preflight="continue">仍然导出</button></div>`,
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
  // 属性只存警告序号：选择器含引号（img[alt=""]），直接写进 HTML 属性会被截断。
  panel.querySelectorAll<HTMLButtonElement>('[data-preflight-target]').forEach((button) => button.addEventListener('click', () => {
    const selector = warnings[Number(button.dataset.preflightTarget)]?.target
    const target = selector ? root.querySelector<HTMLElement>(selector) : null
    target?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    target?.focus?.({ preventScroll: true })
  }))
  return panel
}
