import { createModal } from './modal'
import { readStorage, writeStorage } from './storage'

export interface ExportSettings {
  cover: boolean
  toc: boolean
  headerFooter: boolean
  pageNumbers: boolean
  sources: boolean
  note: string
}

export function createExportSettingsPanel(root: HTMLElement) {
  const modal = createModal({
    root,
    overlayClass: 'export-settings-panel',
    cardClass: 'export-settings-card',
    closeClass: 'export-settings-close',
    closeLabel: '关闭导出设置',
    labelledBy: 'export-settings-title',
    content: `<div class="panel-header">
        <span class="panel-header-icon panel-header-icon--share" aria-hidden="true">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/></svg>
        </span>
        <div>
          <h2 id="export-settings-title">导出设置</h2>
          <p class="panel-subtitle">配置导出内容与版本备注</p>
        </div>
      </div>
      <div class="panel-body export-settings-body"><label><input type="checkbox" name="cover"> 包含封面</label><label><input type="checkbox" name="toc" checked> 包含目录</label><label><input type="checkbox" name="headerFooter" checked> 页眉页脚</label><label><input type="checkbox" name="pageNumbers" checked> 页码</label><label><input type="checkbox" name="sources" checked> 来源编号与附录</label><label class="export-note-field"><span>版本备注</span><textarea name="note" maxlength="200" rows="3" placeholder="例如：运营数据复核后发布"></textarea></label></div>
      <div class="export-settings-actions"><button type="button" class="ui-button ui-button--secondary" data-export-settings="cancel">取消</button><button type="button" class="ui-button ui-button--primary" data-export-settings="confirm">继续导出</button></div>`,
  })
  const dialog = modal.overlay
  const storageKey = `smart-reporting-editor:export-settings:${window.location.pathname}`
  try {
    const saved = JSON.parse(readStorage(storageKey) ?? '{}') as Partial<ExportSettings>
    for (const name of ['cover', 'toc', 'headerFooter', 'pageNumbers', 'sources'] as const) {
      if (typeof saved[name] === 'boolean') dialog.querySelector<HTMLInputElement>(`[name="${name}"]`)!.checked = saved[name]!
    }
    if (typeof saved.note === 'string') dialog.querySelector<HTMLTextAreaElement>('[name="note"]')!.value = saved.note
  } catch { /* ignore malformed preferences */ }
  const close = modal.close
  dialog.querySelector('[data-export-settings="cancel"]')?.addEventListener('click', close)
  return {
    dialog,
    close,
    open() {
      modal.open(dialog.querySelector<HTMLInputElement>('input'))
    },
    setSourcesEnabled(enabled: boolean) {
      const input = dialog.querySelector<HTMLInputElement>('[name="sources"]')!
      input.disabled = !enabled
      if (!enabled) input.checked = false
      input.closest('label')!.hidden = !enabled
    },
    read(): ExportSettings {
      const settings = Object.fromEntries(['cover', 'toc', 'headerFooter', 'pageNumbers', 'sources'].map((name) => [
        name,
        dialog.querySelector<HTMLInputElement>(`[name="${name}"]`)!.checked,
      ])) as unknown as ExportSettings
      settings.note = dialog.querySelector<HTMLTextAreaElement>('[name="note"]')!.value.trim()
      writeStorage(storageKey, JSON.stringify(settings))
      return settings
    },
  }
}
