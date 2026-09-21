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
    content: '<span class="editor-onboarding-step">快速开始</span><h2>三步完成报告</h2><ol><li>点击正文直接编辑 Markdown</li><li>用左侧目录跳转或排序章节</li><li>保存后即可导出 PDF / Word</li></ol><div><button type="button" data-onboarding="dismiss">知道了</button><button type="button" data-onboarding="hide">以后不再提示</button></div>',
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
