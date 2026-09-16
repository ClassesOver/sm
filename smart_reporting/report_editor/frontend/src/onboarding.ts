export function showEditorOnboarding(root: HTMLElement, key: string) {
  const storageKey = `smart-reporting-editor:onboarding:${key}`
  if (localStorage.getItem(storageKey) === 'done') return null
  const panel = document.createElement('section')
  panel.className = 'editor-onboarding'
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-label', '编辑器使用提示')
  panel.innerHTML = '<div class="editor-onboarding-card"><span class="editor-onboarding-step">快速开始</span><h2>三步完成报告</h2><ol><li>点击正文直接编辑 Markdown</li><li>用左侧目录跳转或排序章节</li><li>保存后即可导出 PDF / Word</li></ol><div><button type="button" data-onboarding="dismiss">知道了</button><button type="button" data-onboarding="hide">以后不再提示</button></div></div>'
  root.append(panel)
  const close = (remember: boolean) => { if (remember) localStorage.setItem(storageKey, 'done'); panel.remove() }
  panel.querySelector('[data-onboarding="dismiss"]')?.addEventListener('click', () => close(false))
  panel.querySelector('[data-onboarding="hide"]')?.addEventListener('click', () => close(true))
  return panel
}
