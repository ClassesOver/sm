import { createModal } from './modal'
import { readStorage, writeStorage } from './storage'

export interface ExportSettings {
  cover: boolean
  toc: boolean
  headerFooter: boolean
  pageNumbers: boolean
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
    content: `<h2 id="export-settings-title">导出设置</h2><label><input type="checkbox" name="cover"> 包含封面</label><label><input type="checkbox" name="toc" checked> 包含目录</label><label><input type="checkbox" name="headerFooter" checked> 页眉页脚</label><label><input type="checkbox" name="pageNumbers" checked> 页码</label><label class="export-note-field"><span>版本备注</span><textarea name="note" maxlength="200" rows="3" placeholder="例如：运营数据复核后发布"></textarea></label><div><button type="button" class="ui-button ui-button--secondary" data-export-settings="cancel">取消</button><button type="button" class="ui-button ui-button--primary" data-export-settings="confirm">继续导出</button></div>`,
  })
  const dialog = modal.overlay
  const storageKey = `smart-reporting-editor:export-settings:${window.location.pathname}`
  try {
    const saved = JSON.parse(readStorage(storageKey) ?? '{}') as Partial<ExportSettings>
    for (const name of ['cover', 'toc', 'headerFooter', 'pageNumbers'] as const) {
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
    read(): ExportSettings {
      const settings = Object.fromEntries(['cover', 'toc', 'headerFooter', 'pageNumbers'].map((name) => [
        name,
        dialog.querySelector<HTMLInputElement>(`[name="${name}"]`)!.checked,
      ])) as unknown as ExportSettings
      settings.note = dialog.querySelector<HTMLTextAreaElement>('[name="note"]')!.value.trim()
      writeStorage(storageKey, JSON.stringify(settings))
      return settings
    },
  }
}
