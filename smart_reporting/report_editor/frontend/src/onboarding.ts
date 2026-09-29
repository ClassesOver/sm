import { createModal } from './modal'
import { readStorage, writeStorage } from './storage'

export function showEditorOnboarding(root: HTMLElement, key: string) {
  const storageKey = `smart-reporting-editor:onboarding:${key}`
  if (readStorage(storageKey) === 'done') return null
  let closePanel: () => void = () => {}
  const modal = createModal({
    root,
    overlayClass: 'editor-onboarding',
    cardClass: 'editor-onboarding-card',
    label: '编辑器使用提示',
    onRequestClose: () => closePanel(),
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--violet" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>
        </span>
        <div>
          <h2>三步完成报告</h2>
          <p class="panel-subtitle">快速开始</p>
        </div>
      </div>
      <ol class="editor-onboarding-steps"><li>点击正文直接编辑 Markdown</li><li>用左侧目录跳转章节</li><li>保存后即可导出 PDF / Word</li></ol>
      <div class="editor-onboarding-actions"><button type="button" data-onboarding="dismiss">知道了</button><button type="button" data-onboarding="hide">以后不再提示</button></div>`,
  })
  const panel = modal.overlay
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const close = (remember: boolean) => {
    if (remember) writeStorage(storageKey, 'done')
    modal.remove()
    opener?.focus()
  }
  closePanel = () => close(false)
  modal.open(panel.querySelector<HTMLButtonElement>('[data-onboarding="dismiss"]'))
  panel.querySelector('[data-onboarding="dismiss"]')?.addEventListener('click', () => close(false))
  panel.querySelector('[data-onboarding="hide"]')?.addEventListener('click', () => close(true))
  return panel
}
