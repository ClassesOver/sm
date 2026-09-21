import { conflictLines } from './conflict'
import { createModal } from './modal'

export function createConflictPanel(root: HTMLElement, actions: {
  keepLocal: () => void
  useRemote: () => void
  mergeAndRetry: (markdown: string) => void
}) {
  const modal = createModal({
    root,
    overlayClass: 'conflict-panel',
    cardClass: 'conflict-card',
    closeLabel: '关闭保存冲突',
    role: 'alertdialog',
    labelledBy: 'conflict-title',
    variant: 'warning',
    content: `<h2 id="conflict-title">保存冲突</h2><p>服务器版本已变化，请选择如何处理。</p><div class="conflict-diff"></div><label>合并后的 Markdown<textarea data-conflict="merge" rows="8"></textarea></label><div class="conflict-actions"><button type="button" class="ui-button ui-button--primary" data-conflict="local">保留本地</button><button type="button" class="ui-button ui-button--secondary" data-conflict="remote">采用远端</button><button type="button" class="ui-button ui-button--secondary" data-conflict="merge-retry">合并后重试</button></div>`,
  })
  const panel = modal.overlay
  let opener: HTMLElement | null = null
  const hide = modal.close
  panel.querySelector('[data-conflict="local"]')?.addEventListener('click', () => { actions.keepLocal(); hide() })
  panel.querySelector('[data-conflict="remote"]')?.addEventListener('click', () => { actions.useRemote(); hide() })
  panel.querySelector('[data-conflict="merge-retry"]')?.addEventListener('click', () => {
    const markdown = panel.querySelector<HTMLTextAreaElement>('[data-conflict="merge"]')?.value ?? ''
    actions.mergeAndRetry(markdown)
    hide()
  })
  window.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !panel.hidden) hide() })
  return {
    panel,
    show(base: string, local: string, remote: string) {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      const diff = panel.querySelector<HTMLElement>('.conflict-diff')!
      diff.replaceChildren(...conflictLines(base, local, remote).map((line) => {
        const element = document.createElement('div')
        element.className = `conflict-${line.kind}`
        element.textContent = `${line.kind === 'local' ? '本地' : line.kind === 'remote' ? '远端' : '基准'}：${line.text}`
        return element
      }))
      const merge = panel.querySelector<HTMLTextAreaElement>('[data-conflict="merge"]')
      if (merge) merge.value = local
      modal.open(panel.querySelector<HTMLButtonElement>('[data-conflict="local"]'))
    },
  }
}
