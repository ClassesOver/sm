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
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--warning" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
        </span>
        <div>
          <h2 id="conflict-title">保存冲突</h2>
          <p class="panel-subtitle">服务器版本已变化，请选择如何处理。</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="conflict-diff"></div>
        <label class="conflict-merge">合并后的 Markdown<textarea data-conflict="merge" rows="8"></textarea></label>
      </div>
      <div class="conflict-actions"><button type="button" class="ui-button ui-button--primary" data-conflict="local">保留本地</button><button type="button" class="ui-button ui-button--secondary" data-conflict="remote">采用远端</button><button type="button" class="ui-button ui-button--secondary" data-conflict="merge-retry">合并后重试</button></div>`,
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
