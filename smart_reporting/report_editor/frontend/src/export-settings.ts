export interface ExportSettings {
  cover: boolean
  toc: boolean
  headerFooter: boolean
  pageNumbers: boolean
  note: string
}

import { installFocusTrap } from './focus-trap'

export function createExportSettingsPanel(root: HTMLElement) {
  const dialog = document.createElement('div')
  dialog.className = 'export-settings-panel'
  dialog.hidden = true
  dialog.innerHTML = `<section class="export-settings-card" role="dialog" aria-modal="true" aria-labelledby="export-settings-title"><button type="button" class="export-settings-close" aria-label="关闭导出设置">×</button><h2 id="export-settings-title">导出设置</h2><label><input type="checkbox" name="cover"> 包含封面</label><label><input type="checkbox" name="toc" checked> 包含目录</label><label><input type="checkbox" name="headerFooter" checked> 页眉页脚</label><label><input type="checkbox" name="pageNumbers" checked> 页码</label><label class="export-note-field"><span>版本备注</span><textarea name="note" maxlength="200" rows="3" placeholder="例如：运营数据复核后发布"></textarea></label><div><button type="button" data-export-settings="cancel">取消</button><button type="button" data-export-settings="confirm">继续导出</button></div></section>`
  root.append(dialog)
  const storageKey = `smart-reporting-editor:export-settings:${window.location.pathname}`
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}') as Partial<ExportSettings>
    for (const name of ['cover', 'toc', 'headerFooter', 'pageNumbers'] as const) {
      if (typeof saved[name] === 'boolean') dialog.querySelector<HTMLInputElement>(`[name="${name}"]`)!.checked = saved[name]!
    }
    if (typeof saved.note === 'string') dialog.querySelector<HTMLTextAreaElement>('[name="note"]')!.value = saved.note
  } catch { /* ignore malformed preferences */ }
  installFocusTrap(dialog)
  let opener: HTMLElement | null = null
  const close = () => { dialog.hidden = true; opener?.focus(); opener = null }
  dialog.querySelector('.export-settings-close')?.addEventListener('click', close)
  dialog.querySelector('[data-export-settings="cancel"]')?.addEventListener('click', close)
  window.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !dialog.hidden) close() })
  return {
    dialog,
    open() {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      dialog.hidden = false
      dialog.querySelector<HTMLInputElement>('input')?.focus()
    },
    read(): ExportSettings {
      const settings = Object.fromEntries(['cover', 'toc', 'headerFooter', 'pageNumbers'].map((name) => [
        name,
        dialog.querySelector<HTMLInputElement>(`[name="${name}"]`)!.checked,
      ])) as unknown as ExportSettings
      settings.note = dialog.querySelector<HTMLTextAreaElement>('[name="note"]')!.value.trim()
      localStorage.setItem(storageKey, JSON.stringify(settings))
      return settings
    },
  }
}
